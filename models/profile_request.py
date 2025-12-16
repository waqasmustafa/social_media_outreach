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
        required=False,
        help="Paste the social media profile URL (e.g. Instagram, TikTok, etc.).",
    )
    image_ids = fields.Many2many(
        "ir.attachment",
        string="Profile Images",
        help="Upload one or more profile screenshots (max 3 recommended).",
    )

    @api.constrains('profile_url', 'image_ids')
    def _check_url_or_image(self):
        for record in self:
            if not record.profile_url:
                if not record.image_ids:
                    raise UserError(_("Please provide either a Profile URL or Profile Images."))
                
            if record.image_ids and len(record.image_ids) > 3:
                raise UserError(_("You can upload a maximum of 3 images."))

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

            # Prepare request content
            user_content = record.profile_url if record.profile_url else ""
            image_data = record.profile_image if record.profile_image else None

            record.status = "sending"
            self.env.cr.commit()  # Commit status change so user sees it immediately

            try:
                response_text = record._call_openai_assistant(
                    api_base, api_key, assistant_id, user_content, image_data=image_data
                )

                # Try to parse JSON from assistant response
                parsed_json = None
                parse_error = None
                
                # First try direct parsing
                try:
                    parsed_json = json.loads(response_text)
                except json.JSONDecodeError:
                    # If direct parsing fails, try to find JSON block using regex
                    import re
                    # Look for { ... } structure, allowing for newlines and nested braces roughly
                    # This simple regex finds the first outer-most curly brace block
                    match = re.search(r'(\{.*\})', response_text, re.DOTALL)
                    if match:
                        try:
                            json_str = match.group(1)
                            parsed_json = json.loads(json_str)
                        except Exception as e:
                            parse_error = f"Regex found block but failed to parse: {str(e)}"
                            _logger.warning("Failed to parse extracted JSON: %s", parse_error)
                    else:
                        parse_error = "No JSON object found in response"
                        _logger.warning("Failed to find JSON in Assistant response")

                profile_name = None
                status_msg = "OK"

                if isinstance(parsed_json, dict):
                    # Map 'display_name' from payload to 'profile_name'
                    profile_name = parsed_json.get("display_name") or parsed_json.get("profile_name") or ""
                    # If status is not explicit, we assume OK if we got a valid payload
                    status_msg = parsed_json.get("status") or "OK"

                    # ---------------------------------------------------------
                    # Send to Webhook
                    # ---------------------------------------------------------
                    webhook_url = IrConfig.get_param("social_media_outreach.webhook_url")
                    if webhook_url:
                        try:
                            # increased timeout to 20s for synchronous processing
                            wh_resp = requests.get(webhook_url, params=parsed_json, timeout=20)
                            if wh_resp.status_code == 200:
                                # Capture the actual response from n8n (Respond to Webhook Node)
                                try:
                                    n8n_data = wh_resp.json()
                                    # If it's a dict, maybe show a specific field or dump it safely
                                    # For now, let's dump it as string or take a message field
                                    wh_msg = str(n8n_data)
                                except:
                                    # If not JSON, take raw text
                                    wh_msg = wh_resp.text
                                
                                status_msg += f" | {wh_msg}"
                            else:
                                status_msg += f" | Webhook Failed ({wh_resp.status_code})"
                                _logger.warning("Webhook failed: %s", wh_resp.text)
                        except Exception as wh_error:
                            status_msg += f" | Webhook Error: {str(wh_error)}"
                            _logger.error("Webhook exception: %s", wh_error)
                    else:
                        # Log that no webhook URL is configured, but don't treat as error
                        _logger.info("No webhook URL configured, skipping webhook.")

                # Update main record fields
                record.last_profile_name = profile_name or ""
                record.last_response_status = status_msg
                record.last_sent_at = fields.Datetime.now()
                record.status = "success"

                # Build log message
                log_message = status_msg
                if parse_error:
                    log_message += f" | JSON parse error: {parse_error}"

                # Extract brand and profile_url if available
                brand_name = ""
                extracted_url = ""
                if isinstance(parsed_json, dict):
                    brand_name = parsed_json.get("brand") or ""
                    extracted_url = parsed_json.get("profile_url") or ""
                
                # Use record URL or AI extracted URL
                final_url = record.profile_url or extracted_url

                # Create log line
                self.env["ai.profile.log"].create(
                    {
                        "request_id": record.id,
                        "profile_name": profile_name or "",
                        "brand": brand_name,
                        "profile_url": final_url,
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
                        "brand": "",
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

    def _call_openai_assistant(self, api_base, api_key, assistant_id, user_content, images=None):
        """
        Interacts with OpenAI Assistant API (v2) with Threads.
        Supports both text (URL) and MULTIPLE image inputs.
        """
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "OpenAI-Beta": "assistants=v2",
        }

        # ---------------------------------------------------------
        # 0. Upload Files if images exist
        # ---------------------------------------------------------
        message_content = []
        
        # Add Text Content (URL) if available
        if user_content:
            message_content.append({
                "type": "text",
                "text": f"Social media profile URL: {user_content}\n"
            })
        elif not images:
             # Fallback if somehow both are missing
             message_content.append({
                "type": "text",
                "text": "Please analyze this profile."
            })

        if images:
             # Loop through each image attachment
             for img in images:
                try:
                    import base64
                    # ir.attachment stores data in 'datas' field
                    file_bytes = base64.b64decode(img.datas)
                    
                    upload_url = f"{api_base.rstrip('/')}/files"
                    files = {
                        'file': (img.name or 'screenshot.png', file_bytes, 'image/png'),
                        'purpose': (None, 'vision'),
                    }
                    upload_headers = {
                        "Authorization": f"Bearer {api_key}",
                        "OpenAI-Beta": "assistants=v2", 
                    }
                    
                    upload_resp = requests.post(upload_url, headers=upload_headers, files=files)
                    if upload_resp.status_code >= 400:
                        raise Exception(f"Image upload failed for {img.name}: {upload_resp.text}")
                    
                    file_id = upload_resp.json().get("id")
                    
                    message_content.append({
                        "type": "image_file",
                        "image_file": {"file_id": file_id}
                    })
                except Exception as e:
                    raise UserError(f"Error uploading image {img.name}: {str(e)}")

        # ---------------------------------------------------------
        # 1. Create a Thread with Initial Message
        # ---------------------------------------------------------
        thread_payload = {
            "messages": [
                {
                    "role": "user",
                    "content": message_content
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
    brand = fields.Char(
        string="Brand",
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
