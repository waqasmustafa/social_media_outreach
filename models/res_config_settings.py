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
    social_media_outreach_webhook_url = fields.Char(
        string="Webhook URL",
        help="URL where the parsed JSON data will be sent (e.g. n8n webhook).",
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
            social_media_outreach_webhook_url=IrConfig.get_param(
                "social_media_outreach.webhook_url", default=""
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
        IrConfig.set_param(
            "social_media_outreach.webhook_url",
            self.social_media_outreach_webhook_url or "",
        )

    def action_test_assistant_connection(self):
        """Test OpenAI Assistant connection and save settings."""
        import requests
        from odoo.exceptions import UserError

        # First save the current values
        self.set_values()

        # Validate required fields
        if not self.assistant_openai_api_key:
            raise UserError("Please enter an OpenAI API Key before testing.")
        if not self.assistant_id:
            raise UserError("Please enter an Assistant ID before testing.")

        api_base = self.assistant_api_base or "https://api.openai.com/v1"
        
        try:
            # Test API connection by retrieving the assistant details
            headers = {
                "Authorization": f"Bearer {self.assistant_openai_api_key}",
                "Content-Type": "application/json",
                "OpenAI-Beta": "assistants=v2",
            }
            
            url = f"{api_base.rstrip('/')}/assistants/{self.assistant_id}"
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                assistant_data = response.json()
                assistant_name = assistant_data.get("name", "Unknown")
                
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "Connection Successful!",
                        "message": f"Successfully connected to Assistant: {assistant_name}",
                        "type": "success",
                        "sticky": False,
                    },
                }
            elif response.status_code == 401:
                raise UserError("Invalid API Key. Please check your credentials.")
            elif response.status_code == 404:
                raise UserError("Assistant ID not found. Please verify the Assistant ID.")
            else:
                raise UserError(f"Connection failed with status {response.status_code}: {response.text}")
                
        except requests.exceptions.Timeout:
            raise UserError("Connection timeout. Please check your internet connection.")
        except requests.exceptions.RequestException as e:
            raise UserError(f"Connection error: {str(e)}")
