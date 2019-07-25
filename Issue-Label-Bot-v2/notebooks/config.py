import os
import yaml

class Config:

    def __init__(self, yaml_path=None):
        assert yaml_path, "No configure yaml path"
        self.yaml_path = yaml_path
        self.load()

    def load(self):
        with open(self.yaml_path, 'r') as f:
            config = yaml.safe_load(f)

        self.repo_owner = config['repository']['owner']
        self.repo_name = config['repository']['name']

        self.model_bucket_name = 'repo-models'
        self.emb_bucket_name = 'repo-embeddings'

        self.model_gcs_path = f'{self.repo_owner}/{self.repo_name}.model'
        self.labels_gcs_path = f'{self.repo_owner}/{self.repo_name}.labels'
        self.emb_gcs_path = f'{self.repo_owner}/{self.repo_name}'

        self.model_local_path = f'{self.repo_name}.dpkl'
        self.labels_local_path = f'{self.repo_name}.labels.dpkl'
        self.emb_local_path = f'{self.repo_name}.emb.dpkl'

        ### repo_owner = config['repository']['owner']
        ### repo_name = config['repository']['name']

        ### all_config = {}
        ### all_config['repo_owner'] = config['repository']['owner']
        ### all_config['repo_name'] = config['repository']['name']

        ### all_config['model_bucket_name'] = 'repo-models'
        ### all_config['emb_bucket_name'] = 'repo-embeddings'

        ### all_config['model_gcs_path'] = f'{repo_owner}/{repo_name}.model'
        ### all_config['labels_gcs_path'] = f'{repo_owner}/{repo_name}.labels'
        ### all_config['emb_gcs_path'] = f'{repo_owner}/{repo_name}'

        ### all_config['model_local_path'] = f'{repo_name}.dpkl'
        ### all_config['labels_local_path'] = f'{repo_name}.labels.dpkl'
        ### all_config['emb_local_path'] = f'{repo_name}.emb.dpkl'

        ### return all_config


if __name__ == '__main__':
    config = Config(yaml_path='issue_label_bot.yaml')
    print(config)
    print(config.__dict__)
