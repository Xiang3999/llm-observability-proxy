name: Pull Request
description: Create a pull request
title: ""
labels: []
assignees: []
body:
  - type: markdown
    attributes:
      value: |
        Thanks for contributing! Please fill out this template to help us review your PR.
  - type: textarea
    id: description
    attributes:
      label: Description
      description: What problem does this PR solve? What changes are being made?
    validations:
      required: true
  - type: textarea
    id: related-issues
    attributes:
      label: Related Issues
      description: Link any related issues using #issue_number format.
      placeholder: "Closes #123, Fixes #456"
  - type: textarea
    id: type-of-change
    attributes:
      label: Type of Change
      description: Check all that apply.
      options:
        - label: Bug fix (non-breaking change which fixes an issue)
        - label: New feature (non-breaking change which adds functionality)
        - label: Breaking change (fix or feature that would cause existing functionality to not work as expected)
        - label: Documentation update
        - label: Refactoring (no functional changes)
        - label: Performance improvement
        - label: Test improvements
  - type: checkboxes
    id: checklist
    attributes:
      label: Checklist
      options:
        - label: I have read the [CONTRIBUTING](../CONTRIBUTING.md) document
        - label: My code follows the code style of this project
        - label: I have added tests for my changes
        - label: All tests pass locally
        - label: I have updated the documentation (if needed)
        - label: My changes generate no new warnings
    validations:
      required: true
  - type: textarea
    id: testing
    attributes:
      label: How Has This Been Tested?
      description: Describe the tests you ran to verify your changes.
      placeholder: "Ran pytest tests/unit/..."
  - type: textarea
    id: additional-context
    attributes:
      label: Additional Context
      description: Add any other context about the pull request here.
