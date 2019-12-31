"""Unittest for repo_specific_model. """
import logging
from unittest import mock
import pytest

from label_microservice import mlp
from label_microservice import repo_specific_model
from label_microservice import test_util

def test_predict_labels():
  """A unittest for predict labels.

  This function mocks out the embedding service and the MLPWorker.
  """
  model = repo_specific_model.RepoSpecificLabelModel()

  model._mlp_predictor = mock.MagicMock(spec=mlp.MLPWrapper)
  model._mlp_predictor.predict_probabilities.return_value = [[.2, .9]]

  model._label_names = ["label1", "label2"]
  model._label_thresholds = {
    "label1": .5 ,
    "label2": .5
  }
  model._get_issue_embedding = mock.MagicMock()
  model._get_issue_embedding.return_value = [(10, 10)]

  results = model.predict_issue_labels("some title", "some text")

  expected = {
    "label2": .9,
  }
  test_util.assert_dict_equal(expected, results)


@mock.patch("repo_specific_model.requests.post")
def test_get_issue_embedding_not_found(mock_post):
  "Testing get_issue_embedding function when embedding service returns 404."""

  model = repo_specific_model.RepoSpecificLabelModel()
  model._embedding_api_key = "1234abcd"
  mock_post.return_value.status_code = 404
  issue_embedding = model._get_issue_embedding("title", "text")
  # issue_embedding should be None
  assert not issue_embedding

if __name__ == "__main__":
  logging.basicConfig(
      level=logging.INFO,
      format=('%(levelname)s|%(asctime)s'
              '|%(pathname)s|%(lineno)d| %(message)s'),
      datefmt='%Y-%m-%dT%H:%M:%S',
  )
  logging.getLogger().setLevel(logging.INFO)

  pytest.main()

