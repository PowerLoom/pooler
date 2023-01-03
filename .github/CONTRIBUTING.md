### Contribution Best Practices

* Read this [how-to about Github workflow here](https://guides.github.com/introduction/flow/) if you are not familiar with.

* Read all the texts related to [contributing for an OS community](/.github).

* Read this [how-to about writing a PR](https://github.com/blog/1943-how-to-write-the-perfect-pull-request) and this [other how-to about writing a issue](https://wiredcraft.com/blog/how-we-write-our-github-issues/)

* **first ask in chat**: if you find a problem, first ask for [help in the chat](https://hydraecosystem.slack.com/), then consider opening a issue.

* **read history**: before opening a PR be sure that all the tests pass successfully. If any is failing for non-related reasons, annotate the test failure in the PR comment.

* **PRs on develop**: any change should be PRed first in `develop`, `master` can only receive merge from develop.

* **testing**:  everything should work and be tested for Python 3.6.0 and above.

* **free PR**: no permission is needed to work on the code. Fork `master`, submit a PR and ask for reviewing. PR is the natural place for code comparison and corrections. If many contributors have something ready in a PR, we can consider opening a branch in which different people working on the same part of the application can collaborate.

### For Developers
We use [pre-commit hooks](https://pre-commit.com/) to ensure our code quality is maintained over time. For this contributors need to do a one-time setup by running the following commands.
* Install the required dependencies using `pip install dev-requirements.txt`, this will setup everything needed for pre-commit checks.
* Run `pre-commit install`

Now, whenever you commit anything, it'll automatically check the files you've changed/edited for code quality issues and suggest improvements.
