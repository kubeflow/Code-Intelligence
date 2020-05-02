import logging
import os

from code_intelligence import embeddings
from label_microservice import automl_model
from label_microservice import combined_model
from label_microservice import repo_specific_model
from label_microservice import universal_kind_label_model as universal_model

UNIVERSAL_MODEL_NAME = "universal"

# TODO(jlewi): Lets not hardcode this.
KUBEFLOW_AUTOML_MODEL = "projects/976279526634/locations/us-central1/models/TCN654213816573231104"

def _combined_model_name(org, repo=None):
  """Return the name of the combined model for a repo or organization.

  If repo is specified looks for a repo specific model. If repo is
  none we return an org wide model.

  Args:
    org: Name of the org.
    repo: (Optional) The name of the repo
  """

  if repo:
    return f"{org}/{repo}_combined"
  else:
    return f"{org}_combined"

def _dict_has_keys(d, keys):
  for k in keys:
    if not k in d:
      return False

  return True

class IssueLabelPredictor:
  """Predict labels for an issue.

  This class combines various model classes with logic to fetch information
  about the issue.

  This class doesn't attach the labels to the issues.
  """

  def __init__(self):

    # A dictionary mapping keys to individual models.
    self._models = {}
    self._load_models()

  def _load_models(self):
    """Load the models."""
    logging.info("Loading the universal model")
    self._models[UNIVERSAL_MODEL_NAME] = universal_model.UniversalKindLabelModel()

    # TODO(jlewi): How should we get a list of all models for which we
    # have repo or org specific models. mlbot is doing this based on a config
    # file; https://github.com/machine-learning-apps/Issue-Label-Bot/blob/26d8fb65be3b39de244c4be9e32b2838111dac10/flask_app/forward_utils.py#L5
    for org in ["kubeflow"]:
      logging.info(f"Loading AutoML model for org: {org}; model: {KUBEFLOW_AUTOML_MODEL}")

      org_model = automl_model.AutoMLModel(model_name=KUBEFLOW_AUTOML_MODEL)

      self._models[f"{org}"] = org_model

      combined = combined_model.CombinedLabelModels(
              models=[self._models["universal"], org_model])
      self._models[_combined_model_name(org)] = combined


  def predict_labels_for_data(self, model_name, org, repo, title, body,
                              context=None):
    """Generate label predictions for the specified data.

    Args:
      model_name: Which model to use
      org: org
      repo: Repo name
      title: Title for the issue
      body: body of the issue

    Returns
     dict: str -> float; dictionary mapping labels to their probability
    """
    if not model_name in self._models:
      raise ValueError(f"No model named {model_name}")

    model = self._models[model_name]
    logging.info(f"Generating predictions for title={title} text={body} using"
                 f"model: {model_name} class:{model.__class__}")
    predictions = model.predict_issue_labels(org, repo, title, body,
                                             context=context)

    return predictions

  def predict_labels_for_issue(self, org, repo, issue_number, model_name=None):
    """Generate label predictions for a github issue.

    The function contacts GitHub to collect the required data.

    Args:
      org: The GitHub organization
      repo: The repo that owns the issue
      number: The github issue number
      model_name: (Optional) the name of the model to use to generate
        predictions. if not supplied it is inferred based on the repository.

    Returns
     dict: str -> float; dictionary mapping labels to their probability
    """
    if not model_name:
      org_model = _combined_model_name(org)
      repo_model = _combined_model_name(org, repo)

      if repo_model in self._models:
        model_name = repo_model
      elif org_model in self._models:
        model_name = org_model
      else:
        model_name = UNIVERSAL_MODEL_NAME

    logging.info(f"Predict labels for "
                 f"{org}/{repo}#{issue_number} using "
                 f"model {model_name}")

    data = embeddings.get_issue_text(issue_number, None, org, repo)

    if not data.get("title"):
      logging.warning(f"Got empty title for {org}/{repo}#{issue_number}")

    if not data.get("body"):
      logging.warning(f"Got empty title for {org}/{repo}#{issue_number}")

    context={
      "repo_owner": org,
      "repo_name": repo,
      "issue_num": issue_number,
    }

    predictions = self.predict_labels_for_data(
      model_name, org, repo, data.get("title"), [data.get("body")],
      context=context)

    return predictions

  def predict(self, data):
    """Generate predictions for the specified payload.

    Args: data a dictionary containing the data to generate predictions for.
    The payload can either look like

        {
          "title": "some issue title"
          "text": "text for some issue
          "model_name": Name of model to use
          ...
        }

        in this case predictions will be generated for this title and text.

        or

        {
          "repo_owner": <GitHub owner of the issue>
          "repo_name": <GitHub repo>
          "issue_num": <Issue number>
          "model_name": (optional) name of the model to use
          ...
        }
    """
    text_keys = ["title", "text", "model_name"]
    issue_keys = ["repo_owner", "repo_name", "issue_num"]
    if _dict_has_keys(data, text_keys):
      return self.predict_labels_for_data(data["model_name"], data["title"],
                                          data["text"])
    elif _dict_has_keys(data, issue_keys):
      return self.predict_labels_for_issue(data["repo_owner"],
                                           data["repo_name"],
                                           data["issue_num"],
                                           model_name=data.get("model_name"))
    else:
      actual = ",".join(data.keys())
      text_str = ",".join(text_keys)
      issue_str = ",".join(issue_keys)
      want = f"[{text_str}] or [{issue_str}]"
      logging.error(f"Data is missing required keys; got {actual}; want {want}")
      raise ValueError(f"Data is missing required keys; got {actual}; want {want}")

