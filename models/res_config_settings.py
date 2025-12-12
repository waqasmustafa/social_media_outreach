import requests
from odoo import api, fields, models, _
from odoo.exceptions import UserError


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

    def action_test_connection(self):
        """
        Test the OpenAI Assistant connection by verifying the Assistant ID exists.
        If successful, save the credentials and show success message.
        """
        self.ensure_one()

        # Validate required fields
        if not self.assistant_openai_api_key:
            raise UserError(_("Please enter an OpenAI API Key before testing."))
        if not self.assistant_id:
            raise UserError(_("Please enter an Assistant ID before testing."))

        api_base = self.assistant_api_base or "https://api.openai.com/v1"
        
        # Prepare headers
        headers = {
            "Authorization": f"Bearer {self.assistant_openai_api_key}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "assistants=v2",
        }

        # Try to retrieve the assistant to verify credentials
        assistant_url = f"{api_base.rstrip('/')}/assistants/{self.assistant_id}"
        
        try:
            response = requests.get(assistant_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                assistant_data = response.json()
                assistant_name = assistant_data.get("name", "Unknown")
                model = assistant_data.get("model", "Unknown")
                
                # Save the settings
                self.set_values()
                
                # Show success message
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Connection Successful!'),
                        'message': _(
                            f'Successfully connected to Assistant: {assistant_name}\n'
                            f'Model: {model}\n'
                            f'Settings have been saved.'
                        ),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            elif response.status_code == 401:
                raise UserError(_("Invalid API Key. Please check your credentials."))
            elif response.status_code == 404:
                raise UserError(_(
                    "Assistant ID not found. Please verify the Assistant ID is correct."
                ))
            else:
                raise UserError(_(
                    f"Connection failed with status {response.status_code}: {response.text}"
                ))
                
        except requests.exceptions.Timeout:
            raise UserError(_("Connection timeout. Please check your internet connection."))
        except requests.exceptions.RequestException as e:
            raise UserError(_(f"Connection error: {str(e)}"))
