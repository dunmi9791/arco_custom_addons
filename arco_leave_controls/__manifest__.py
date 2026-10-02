{
    "name": "ARCO Leave Controls",
    "version": "18.0.1.0.0",
    "summary": "SMERP leave workflow: Manager approval then HR review, HR notified on every request, "
    "reminders to managers on pending requests; balance and overlap checks, calendar update",
    "author": "Secteur Network Solutions",
    "category": "ARCO",
    "license": "LGPL-3",
    "depends": ["arco_base", "hr_holidays"],
    "data": [
        "data/cron.xml",
        "views/leave_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
}
