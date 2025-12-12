from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    assistant_openai_api_key = fields.Char(
        string="OpenAI API Key",
        help="API key used to connect to OpenAI Assistant (stored in system parameters).",
    )
    assistant_id = fields.Char(
        string="Assistant ID",
        help="The ID of the OpenAI Assistant (e.g. asst_123...).",
    )
    assistant_model = fields.Char(
        string="Model Name",
        default="gpt-5.1",
        help="Model used by the Assistant (for reference).",
    )
    assistant_api_base = fields.Char(
        string="API Base URL",
        default="https://api.openai.com/v1",
        help="Base URL for the OpenAI API. Leave default unless using a custom endpoint.",
    )

    @api.model
    def get_values(self):
        res = super().get_values()
        IrConfig = self.env["ir.config_parameter"].sudo()
        res.update(
            assistant_openai_api_key=IrConfig.get_param(
                "social_media_outreach.assistant_openai_api_key", default=""
            ),
            assistant_id=IrConfig.get_param(
                "social_media_outreach.assistant_id", default=""
            ),
            assistant_model=IrConfig.get_param(
                "social_media_outreach.assistant_model", default="gpt-5.1"
            ),
            assistant_api_base=IrConfig.get_param(
                "social_media_outreach.assistant_api_base",
                default="https://api.openai.com/v1",
            ),
        )
        return res

    def set_values(self):
        super().set_values()
        IrConfig = self.env["ir.config_parameter"].sudo()
        IrConfig.set_param(
            "social_media_outreach.assistant_openai_api_key",
            self.assistant_openai_api_key or "",
        )
        IrConfig.set_param(
            "social_media_outreach.assistant_id",
            self.assistant_id or "",
        )
        IrConfig.set_param(
            "social_media_outreach.assistant_model",
            self.assistant_model or "gpt-5.1",
        )
        IrConfig.set_param(
            "social_media_outreach.assistant_api_base",
            self.assistant_api_base or "https://api.openai.com/v1",
        )
