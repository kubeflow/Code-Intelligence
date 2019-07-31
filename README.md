# Code Intelligence: ML-Powered Developer Tools
Made with [Kubeflow](https://www.kubeflow.org/)

### **Motivation:**
One of the promises of machine learning is to automate mundane tasks and augment our capabilities, making us all more productive.  However, one domain that doesn’t get much attention that is ripe for more automation is the domain of software development itself.  This repository contains projects that are **live machine learning-powered devloper tools, usually in the form of GitHub apps, plugins or APIs.**  

We build these tools with the help of Kubeflow, in order to dog-food tools that Kubeflow developers themselves will benefit from, but also to surface real-world examples of end-to-end machine learning applications built with Kubeflow.

# Projects

### Deployed

1. [Issue-Label-Bot](https://github.com/marketplace/issue-label-bot): A GitHub App that automatically labels issues as either a feature request, bug or question, using machine learning.  The code for this is located in [this repository](https://github.com/machine-learning-apps/Issue-Label-Bot)

2. [Issue-Embeddings](/Issue-Embeddings): A REST-API that returns 2400 dimensional embedding given an issue title and body.  This can be used for several downstream applications such as (1) label prediction, (2) duplicate detection (3) reviewer recommendation, etc.  You can also retrieve the embeddings for all issues in a repo in bulk at once.

### Under Construction :construction:

1. [Label-Microservice](/Label-Microservice): A stand-alone service that receives as input an issue url: _example: `github.com/kubeflow/<repo>/issues/<issue_num>_` and returns repo-specific label predictions.  This leverages transfer learning via the [Issue-Embeddings](/Issue-Embeddings) API.  The goal of this project is to prototype this functionality by redirecting a subset of traffic from Issue-Label-Bot (starting with just Kubeflow/Kubeflow) for testing.

2. Notifications: TODO

# Developer Guide

## Code Organization

We are in the process of organizing all Python code under the directory `py/`. 

* Subdirectories of `py/` should be top level packages
* Modules should be imported using absolute imports always
