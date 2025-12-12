import json
import logging
import time

import requests

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AiProfileRequest(models.Model):
    _name = "ai.profile.request"
    _description = "AI Social Profile Request"
    _order = "create_date desc"

    name = fields.Char(
        string="Name",
        default=lambda self: _("Social Profile"),
        help="Internal name for this profile request.",
    )
    profile_url = fields.Char(
        string="Profile URL",
        required=True,
        help="Paste the social media profile URL (e.g. Instagram, TikTok, etc.).",
    )
    profile_image = fields.Binary(
        string="Profile Image",
        help="Optional profile image (if URL is not enough). Currently only logged, not sent as file.",
    )

    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("sending", "Sending"),
            ("success", "Success"),
            ("failed", "Failed"),
        ],
        string="Status",
        default="draft",
        readonly=False,
    )

    last_profile_name = fields.Char(
        string="Last Profile Name",
        readonly=True,
        help="Profile name returned by the Assistant in the last call.",
    )
    last_response_status = fields.Char(
        string="Last Response Status",
        readonly=True,
        help="Short summary or status of the last Assistant response.",
    )
    last_sent_at = fields.Datetime(
        string="Last Sent At",
        readonly=True,
    )

    log_ids = fields.One2many(
        "ai.profile.log",
        "request_id",
        string="Logs",
        readonly=True,
    )

    def action_send_now(self):
        """
        Button: send profile URL (and optional image info) to the AI Assistant.
        Logs the response and updates status fields.
        """
        for record in self:
            if not record.profile_url:
                raise UserError(_("Please provide a Profile URL before sending."))

            # Load configuration
            IrConfig = self.env["ir.config_parameter"].sudo()
            api_key = IrConfig.get_param(
                "social_media_outreach.assistant_openai_api_key"
            )
            assistant_id = IrConfig.get_param("social_media_outreach.assistant_id")
            api_base = IrConfig.get_param(
                "social_media_outreach.assistant_api_base",
                default="https://api.openai.com/v1",
            )

            if not api_key or not assistant_id:
                raise UserError(
                    _(
                        "OpenAI Assistant is not configured.\n"
                        "Please set API Key and Assistant ID in Settings > General Settings > AI Assistant Connector."
                    )
                )

            # Prepare request content for the Assistant
            # NOTE: Right now we are sending only URL in text.
            # Image is not being sent as a file to OpenAI in this version.
            user_content = f"Social media profile URL: {record.profile_url}\n"
            if record.profile_image:
                user_content += (
                    "A profile image is also available in Odoo for this record.\n"
                )

            record.status = "sending"
            self.env.cr.commit()  # Commit status change so user sees it immediately

            try:
                response_text = record._call_openai_assistant(
                    api_base=api_base,
                    api_key=api_key,
                    assistant_id=assistant_id,
                    user_content=user_content,
                )

                # Try to parse JSON from assistant response
                parsed_json = None
                parse_error = None
                try:
                    parsed_json = json.loads(response_text)
                except Exception as e:
                    parse_error = str(e)
                    _logger.warning(
                        "Failed to parse Assistant JSON response: %s", parse_error
                    )

                profile_name = None
                status_msg = "OK"

                if isinstance(parsed_json, dict):
                    profile_name = parsed_json.get("profile_name") or ""
                    status_msg = parsed_json.get("status") or "OK"

                # Update main record fields
                record.last_profile_name = profile_name or ""
                record.last_response_status = status_msg
                record.last_sent_at = fields.Datetime.now()
                record.status = "success"

                # Build log message
                log_message = status_msg
                if parse_error:
                    log_message += f" | JSON parse error: {parse_error}"

                # Create log line
                self.env["ai.profile.log"].create(
                    {
                        "request_id": record.id,
                        "profile_name": profile_name or "",
                        "profile_url": record.profile_url,
                        "status": "success",
                        "message": log_message,
                        "response_json": response_text,
                        "sent_at": fields.Datetime.now(),
                    }
                )

            except Exception as e:
                error_msg = str(e)
                _logger.exception("Error calling OpenAI Assistant: %s", error_msg)

                record.status = "failed"
                record.last_response_status = error_msg
                record.last_sent_at = fields.Datetime.now()

                # Log failed attempt
                self.env["ai.profile.log"].create(
                    {
                        "request_id": record.id,
                        "profile_name": "",
                        "profile_url": record.profile_url,
                        "status": "failed",
                        "message": error_msg,
                        "response_json": "",
                        "sent_at": fields.Datetime.now(),
                    }
                )

                raise UserError(
                    _(
                        "Failed to contact the Assistant.\nTechnical details: %s"
                        % error_msg
                    )
                )

    def _call_openai_assistant(self, api_base, api_key, assistant_id, user_content):
        """
        Low-level helper to call OpenAI Assistants API (v2-style) using HTTP.
        - Creates a thread
        - Adds the user message
        - Starts a run
        - Polls until completion
        - Retrieves the latest assistant message text

        Returns: assistant message text (string)
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "assistants=v2",
        }

        # 1) Create a thread with initial user message
        thread_payload = {
            "messages": [
                {
                    "role": "user",
                    "content": user_content,
                }
            ]
        }

        thread_url = f"{api_base.rstrip('/')}/threads"
        thread_resp = requests.post(thread_url, headers=headers, json=thread_payload)
        if thread_resp.status_code >= 400:
            raise UserError(
                _(
                    "Failed to create Assistant thread. HTTP %s: %s"
                    % (thread_resp.status_code, thread_resp.text)
                )
            )

        thread_data = thread_resp.json()
        thread_id = thread_data.get("id")
        if not thread_id:
            raise UserError(_("Assistant thread ID missing in API response."))

        # 2) Create a run for that thread
        run_url = f"{api_base.rstrip('/')}/threads/{thread_id}/runs"
        run_payload = {
            "assistant_id": assistant_id,
        }

        run_resp = requests.post(run_url, headers=headers, json=run_payload)
        if run_resp.status_code >= 400:
            raise UserError(
                _(
                    "Failed to start Assistant run. HTTP %s: %s"
                    % (run_resp.status_code, run_resp.text)
                )
            )

        run_data = run_resp.json()
        run_id = run_data.get("id")
        if not run_id:
            raise UserError(_("Assistant run ID missing in API response."))

        # 3) Poll run status
        run_status_url = f"{api_base.rstrip('/')}/threads/{thread_id}/runs/{run_id}"

        max_wait_seconds = 60  # safety limit
        poll_interval = 3
        waited = 0

        while True:
            time.sleep(poll_interval)
            waited += poll_interval

            status_resp = requests.get(run_status_url, headers=headers)
            if status_resp.status_code >= 400:
                raise UserError(
                    _(
                        "Failed to poll Assistant run. HTTP %s: %s"
                        % (status_resp.status_code, status_resp.text)
                    )
                )

            status_data = status_resp.json()
            status = status_data.get("status")

            if status in ("completed", "requires_action"):
                break
            if status in ("failed", "cancelled", "expired"):
                raise UserError(_("Assistant run ended with status: %s") % status)
            if waited >= max_wait_seconds:
                raise UserError(_("Assistant run timeout after %s seconds") % waited)

        # 4) Fetch thread messages (latest assistant message)
        messages_url = f"{api_base.rstrip('/')}/threads/{thread_id}/messages"
        messages_resp = requests.get(
            messages_url,
            headers=headers,
            params={"limit": 10},  # last few messages
        )
        if messages_resp.status_code >= 400:
            raise UserError(
                _(
                    "Failed to fetch Assistant messages. HTTP %s: %s"
                    % (messages_resp.status_code, messages_resp.text)
                )
            )

        messages_data = messages_resp.json()
        data_list = messages_data.get("data", [])

        # Find the most recent assistant message
        for msg in data_list:
            if msg.get("role") == "assistant":
                contents = msg.get("content", [])
                # Expect text content type
                for item in contents:
                    if item.get("type") == "text":
                        text_data = item.get("text", {})
                        return text_data.get("value", "")

        # Fallback if nothing found
        return ""


class AiProfileLog(models.Model):
    _name = "ai.profile.log"
    _description = "AI Social Profile Log"
    _order = "sent_at desc, id desc"

    request_id = fields.Many2one(
        "ai.profile.request",
        string="Profile Request",
        ondelete="cascade",
        required=True,
    )
    profile_name = fields.Char(
        string="Profile Name",
    )
    profile_url = fields.Char(
        string="Profile URL",
    )
    status = fields.Selection(
        [
            ("success", "Success"),
            ("failed", "Failed"),
        ],
        string="Status",
        required=True,
    )
    message = fields.Text(
        string="Message",
        help="Short message or error description.",
    )
    response_json = fields.Text(
        string="Raw Response JSON",
        help="Full text response returned by the Assistant.",
    )
    sent_at = fields.Datetime(
        string="Sent At",
        required=True,
    )
