+++
id = "pb-09"
title = "Open feedback in design reviews"
status = "spec"
questions = ["How many feedback items are still open in the design reviews of the battery tray project?"]
tools = ["DesignReview.list", "DesignFeedback.list", "DesignFile.get"]
tasks = []
triggers = ["on_request"]
writes = false
+++

# PB-09 · Open feedback in design reviews

## Use case

A review lead needs the state of each review on a project: its status, its due date, and how much feedback is still open.

## Design

Read the file to get its project. Read the reviews of that project, then the feedback of each review. Count open items by severity in code. Compare `resolved_feedback` on the review with the count from the feedback rows, and flag a difference.
