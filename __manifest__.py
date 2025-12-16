{
    "name": "Social Media Outreach",
    "summary": "Send social media profile URLs & images to AI Assistant and track logs.",
    "version": "18.0.1.0.0",
    "author": "Waqas Mustafa",
    "license": "LGPL-3",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/profile_request_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "assets": {},
    "installable": True,
    "application": True,
}