from . import models


def post_init_hook(env):
    """Two-step validation (employee's approver, then Time Off officer) on every leave type
    that currently needs a single approval."""
    env["hr.leave.type"].with_context(active_test=False).search(
        [("leave_validation_type", "in", ("hr", "manager"))]
    ).write({"leave_validation_type": "both"})
