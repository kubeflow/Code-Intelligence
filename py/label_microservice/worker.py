import os
import fire
import requests
import yaml
import numpy as np
from passlib.apps import custom_app_context as pwd_context
from google.cloud import pubsub
import logging
from label_microservice.repo_config import RepoConfig
from label_microservice.mlp import MLPWrapper
from code_intelligence.github_util import init as github_init
from code_intelligence.github_util import get_issue_handle
from code_intelligence.github_util import get_yaml
from code_intelligence.embeddings import get_issue_text
from code_intelligence.gcs_util import download_file_from_gcs
from code_intelligence.pubsub_util import check_subscription_name_exists
from code_intelligence.pubsub_util import create_subscription_if_not_exists

class Worker:
    """
    The worker class aims to do label prediction for issues from github repos.
    The processes are the following:
    Listen to events in Google Cloud PubSub.
    Load the model mapped to the current event.
    Generate label prediction and check thresholds.
    Call GitHub API to add labels if needed.
    """

    def __init__(self,
                 project_id='issue-label-bot-dev',
                 topic_name='event_queue',
                 subscription_name='subscription_for_event_queue',
                 embedding_api_endpoint='https://embeddings.gh-issue-labeler.com/text'):
        """
        Initialize the parameters and GitHub app.
        Args:
          project_id: gcp project id, str
          topic_name: pubsub topic name, str
          subscription_name: pubsub subscription name, str
          embedding_api_endpoint: endpoint of embedding api microservice, str
        """
        # TODO(chunhsiang): change the embedding microservice to be an internal DNS of k8s service.
        #   see: https://v1-12.docs.kubernetes.io/docs/concepts/services-networking/dns-pod-service/#services
        self.project_id = project_id
        self.topic_name = topic_name
        self.subscription_name = subscription_name
        self.embedding_api_endpoint = embedding_api_endpoint
        self.embedding_api_key = os.environ['GH_ISSUE_API_KEY']
        self.app_url = os.environ['APP_URL']

        # init GitHub app
        github_init()
        # init pubsub subscription
        self.create_subscription_if_not_exists()

    def load_yaml(self, repo_owner, repo_name):
        """
        Load config from the YAML of the specific repo_owner/repo_name.
        Args:
          repo_owner: str
          repo_name: str
        """
        # TODO(chunhsiang): for now all the paths including gcs and local sides
        #   are set using repo_owner/repo_name (see repo_config.py), meaning the
        #   paths returned from `RepoConfig(...)` are related to the specific
        #   repo_owner/repo_name.
        #   Will update them after finish the config map.
        self.config = RepoConfig(repo_owner=repo_owner, repo_name=repo_name)

    def check_subscription_name_exists(self):
        """
        Check if the subscription name exists in the project.

        Return
        ------
        bool
            subscription_name exists in the project or not
        """
        return check_subscription_name_exists(self.project_id, self.subscription_name)

    def create_subscription_if_not_exists(self):
        """
        Create a new pull subscription on the topic if not exists.

        While multiple subscribers listen to the same subscription,
        subscribers receive a subset of the messages.
        """
        create_subscription_if_not_exists(self.project_id, self.topic_name, self.subscription_name)

    def subscribe(self):
        """
        Receive messages from a pull subscription.
        When the subscriber receives a message from pubsub,
        it will call the `callback` function to do label
        prediction and add labels to the issue.
        """
        subscriber = pubsub.SubscriberClient()
        subscription_path = subscriber.subscription_path(self.project_id,
                                                         self.subscription_name)

        def callback(message):
            """
            Address events in pubsub by sequential procedures.
            Load the model mapped to the events.
            Do label prediction.
            Add labels if the confidence is enough.
            Args:
              Object:
              message =
                  Message {
                      data: b'New issue.',
                      attributes: {
                          'installation_id': '10000',
                          'repo_owner': 'kubeflow',
                          'repo_name': 'examples',
                          'issue_num': '1'
                      }
                  }
            """
            installation_id = message.attributes['installation_id']
            repo_owner = message.attributes['repo_owner']
            repo_name = message.attributes['repo_name']
            issue_num = message.attributes['issue_num']
            logging.info(f'Receive issue #{issue_num} from {repo_owner}/{repo_name}')

            try:
                # predict labels
                self.load_yaml(repo_owner, repo_name)
                self.download_model_from_gcs()
                predictions, issue_embedding = self.predict_labels(repo_owner, repo_name, issue_num)
                self.add_labels_to_issue(installation_id, repo_owner, repo_name,
                                         issue_num, predictions)

                # log the prediction, which will be used to track the performance
                log_dict = {
                    'repo_owner': repo_owner,
                    'repo_name': repo_name,
                    'issue_num': int(issue_num),
                    'labels': predictions['labels']
                }
                logging.info(log_dict)

            except Exception as e:
                # hard to find out which errors should be handled differently (e.g., retrying for multiple times)
                # and how to handle the error that the same message causes for multiple times
                # so use generic exception to ignore all errors for now
                logging.error(f'Addressing issue #{issue_num} from {repo_owner}/{repo_name} causes an error')
                logging.error(f'Error type: {type(e)}')
                logging.error(e)

            # acknowledge the message, or pubsub will repeatedly attempt to deliver it
            message.ack()

        # limit the subscriber to only have one outstanding message at a time
        flow_control = pubsub.types.FlowControl(max_messages=1)
        future = subscriber.subscribe(subscription_path,
                                      callback=callback,
                                      flow_control=flow_control)
        try:
            logging.info(future.result())
        except KeyboardInterrupt:
            logging.info(future.cancel())

    def get_issue_embedding(self, repo_owner, repo_name, issue_num):
        """
        Get the embedding of the issue by calling GitHub Issue
        Embeddings API endpoint.
        Args:
          repo_owner: repo owner
          repo_name: repo name
          issue_num: issue index

        Return
        ------
        numpy.ndarray
            shape: (1600,)
        """

        issue_text = get_issue_text(owner=repo_owner,
                                    repo=repo_name,
                                    num=issue_num,
                                    idx=None)
        data = {'title': issue_text['title'],
                'body': issue_text['body']}

        # sending post request and saving response as response object
        r = requests.post(url=self.embedding_api_endpoint,
                          headers={'Token': pwd_context.hash(self.embedding_api_key)},
                          json=data)
        if r.status_code != 200:
            logging.warning(f'Status code is {r.status_code} not 200: '
                            'can not retrieve the embedding')
            return None

        embeddings = np.frombuffer(r.content, dtype='<f4')[:1600]
        return embeddings

    def download_model_from_gcs(self):
        """Download the model from GCS to local path."""
        # download model
        download_file_from_gcs(self.config.model_bucket_name,
                               self.config.model_gcs_path,
                               self.config.model_local_path)

        # download lable columns
        download_file_from_gcs(self.config.model_bucket_name,
                               self.config.labels_gcs_path,
                               self.config.labels_local_path)

    def load_label_columns(self):
        """
        Load label info from local path.

        Return
        ------
        dict
            {'labels': list, 'probability_thresholds': {label_index: threshold}}
        """
        with open(self.config.labels_local_path, 'r') as f:
            label_columns = yaml.safe_load(f)
        return label_columns

    def predict_issue_probability(self, repo_owner, repo_name, issue_num):
        """
        Predict probabilities of labels for an issue.
        Args:
          repo_owner: repo owner
          repo_name: repo name
          issue_num: issue index

        Return
        ------
        numpy.ndarray
            shape: (label_count,)
        numpy.ndarray
            shape: (1600,)
        """
        issue_embedding = self.get_issue_embedding(repo_owner=repo_owner,
                                                   repo_name=repo_name,
                                                   issue_num=issue_num)

        # if not retrieve the embedding, ignore to predict it
        if issue_embedding is None:
            return [], None

        mlp_wrapper = MLPWrapper(clf=None,
                                 model_file=self.config.model_local_path,
                                 load_from_model=True)
        # change embedding from 1d to 2d for prediction and extract the result
        label_probabilities = mlp_wrapper.predict_probabilities([issue_embedding])[0]
        return label_probabilities, issue_embedding

    def predict_labels(self, repo_owner, repo_name, issue_num):
        """
        Predict labels for given issue.
        Args:
          repo_owner: repo owner
          repo_name: repo name
          issue_num: issue index

        Return
        ------
        dict
            {'labels': list, 'probabilities': list}
        numpy.ndarray
            shape: (1600,)
        """
        logging.info(f'Predicting labels for the issue #{issue_num} from {repo_owner}/{repo_name}')
        # get probabilities of labels for an issue
        label_probabilities, issue_embedding = self.predict_issue_probability(repo_owner, repo_name, issue_num)

        # get label info from local file
        label_columns = self.load_label_columns()
        label_names = label_columns['labels']
        label_thresholds = label_columns['probability_thresholds']

        # check thresholds to get labels that need to be predicted
        predictions = {'labels': [], 'probabilities': []}
        for i in range(len(label_probabilities)):
            # if the threshold of any label is None, just ignore it
            # because the label does not meet both of precision & recall thresholds
            if label_thresholds[i] and label_probabilities[i] >= label_thresholds[i]:
                predictions['labels'].append(label_names[i])
                predictions['probabilities'].append(label_probabilities[i])
        return predictions, issue_embedding

    def filter_specified_labels(self, repo_owner, repo_name, predictions):
        """
        Only select those labels which are specified by yaml file to be predicted.
        If there is no setting in the yaml file, return all predicted items.
        Args:
          repo_owner: repo owner, str
          repo_name: repo name, str
          prediction: predicted result from `predict_labels()` function
                      dict {'labels': list, 'probabilities': list}
        """
        label_names = []
        label_probabilities = []
        # handle the yaml file
        yaml = get_yaml(owner=repo_owner, repo=repo_name)
        # user may set the labels they want to predict
        if yaml and 'predicted-labels' in yaml:
            for name, proba in zip(predictions['labels'], predictions['probabilities']):
                if name in yaml['predicted-labels']:
                    label_names.append(name)
                    label_probabilities.append(proba)
        else:
            logging.warning(f'YAML file does not contain `predicted-labels`, '
                             'bot will predict all labels with enough confidence')
            # if user do not set `predicted-labels`,
            # predict all labels with enough confidence
            label_names = predictions['labels']
            label_probabilities = predictions['probabilities']
        return label_names, label_probabilities

    def add_labels_to_issue(self, installation_id, repo_owner, repo_name,
                            issue_num, predictions):
        """
        Add predicted labels to issue using GitHub API.
        Args:
          installation_id: repo installation id
          repo_owner: repo owner
          repo_name: repo name
          issue_num: issue index
          prediction: predicted result from `predict_labels()` function
                      dict {'labels': list, 'probabilities': list}
        """
        # take an action if the prediction is confident enough
        if predictions['labels']:
            label_names, label_probabilities = self.filter_specified_labels(repo_owner,
                                                                            repo_name,
                                                                            predictions)
        else:
            label_names = []

        # get the isssue handle
        issue = get_issue_handle(installation_id, repo_owner, repo_name, issue_num)

        if label_names:
            # create message
            message = """Issue-Label Bot is automatically applying the labels `{labels}` to this issue, with the confidence of {confidence}.
            Please mark this comment with :thumbsup: or :thumbsdown: to give our bot feedback!
            Links: [app homepage](https://github.com/marketplace/issue-label-bot), [dashboard]({app_url}data/{repo_owner}/{repo_name}) and [code](https://github.com/hamelsmu/MLapp) for this bot.
            """.format(labels="`, `".join(label_names),
                       confidence=", ".join(["{:.2f}".format(p) for p in label_probabilities]),
                       app_url=self.app_url,
                       repo_owner=repo_owner,
                       repo_name=repo_name)
            # label the issue using the GitHub api
            issue.add_labels(*label_names)
            logging.info(f'Add `{"`, `".join(label_names)}` to the issue # {issue_num}')
        else:
            message = """Issue Label Bot is not confident enough to auto-label this issue.
            See [dashboard]({app_url}data/{repo_owner}/{repo_name}) for more details.
            """.format(app_url=self.app_url,
                       repo_owner=repo_owner,
                       repo_name=repo_name)
            logging.warning(f'Not confident enough to label this issue: # {issue_num}')

        # make a comment using the GitHub api
        comment = issue.create_comment(message)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO,
                        format=('%(levelname)s|%(asctime)s'
                                '|%(message)s|%(pathname)s|%(lineno)d|'),
                        datefmt='%Y-%m-%dT%H:%M:%S',
                        )

    fire.Fire(Worker)
