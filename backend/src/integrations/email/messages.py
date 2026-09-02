"""The two messages this service sends, and their wording.

Kept apart from the transport because they are a different kind of thing: the
transport is plumbing, this is what a customer reads.

Both say the same three things, in the same order, because both are sent to
someone who may not have asked for them: what the code is for, how long it
lives, and what to do if it was not them. The last line is the one that
matters — an unexpected recovery mail is the earliest warning a person gets
that somebody is trying their address, and a mail that omits it wastes that.
The reference design this follows has no such line; it is kept anyway, small
and under the code, because losing it costs a warning and saves nothing.

**Neither message contains a link, and neither loads an image.** A code the
person retypes cannot be clicked from a phishing copy of this mail, and there
is no URL for a mail client to rewrite or a scanner to visit — which is how
one-click reset links get consumed before the human sees them. The logo is
drawn with a background colour and a letter rather than fetched, so nothing
here reports back when the mail is opened and nothing breaks when a client
blocks remote content by default.

Each message carries a plain-text body *and* an HTML alternative. The text
part is authoritative — see :class:`EmailMessage` — and is what a developer
reads out of the log when the relay is off.
"""

from __future__ import annotations

from html import escape

from src.integrations.email.transport import EmailMessage

#: The brand mark, matching `AppHeaderNext.vue` and `favicon.svg`: the letter
#: on the indigo tile, then the wordmark. Drawn in HTML because an <img> in a
#: mail is either a remote fetch (blocked by default, and a read receipt for
#: whoever hosts it) or an attachment (which shows up as a paperclip on a
#: message that has no files).
#:
#: Cyrillic Em, not Latin M — the same glyph the header renders, and the
#: reason ruff's ambiguous-character rule is silenced on the next line rather
#: than obeyed.
_MARK = "\u041c"
_INDIGO = "#4f46e5"
_INK = "#0f172a"
_MUTED = "#64748b"
_HAIRLINE = "#e2e8f0"


def _shell(*, heading: str, code: str, ttl_minutes: int, footer: str) -> str:
    """Render one message body as HTML.

    Both mails are the same page with different words, so the layout lives
    here once. Tables and inline styles throughout — the usual constraint of
    the medium, where a stylesheet is stripped and flexbox is not understood.

    Args:
        heading: The line above the code.
        code: The plaintext code, shown spaced out so it can be read back.
        ttl_minutes: How long the code stays valid.
        footer: The "if this was not you" sentence, which differs per flow.

    Returns:
        A complete HTML document.
    """
    spaced = " ".join(escape(code))
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#f8fafc;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
         style="background:#f8fafc;padding:32px 12px;">
    <tr><td align="center">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
             style="max-width:560px;background:#ffffff;border:1px solid {_HAIRLINE};
                    border-radius:14px;padding:40px 32px;font-family:-apple-system,
                    BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
        <tr><td align="center" style="padding-bottom:32px;">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
            <td style="background:{_INDIGO};border-radius:9px;width:34px;height:34px;
                       text-align:center;vertical-align:middle;color:#ffffff;
                       font-size:19px;font-weight:700;line-height:34px;">{_MARK}</td>
            <td style="padding-left:11px;font-size:19px;font-weight:600;color:{_INK};
                       white-space:nowrap;">Аналитика<span style="color:{_MUTED};
                       font-weight:500;"> · WB</span></td>
          </tr></table>
        </td></tr>
        <tr><td align="center"
                style="font-size:21px;font-weight:700;color:{_INK};padding-bottom:28px;">
          {escape(heading)}
        </td></tr>
        <tr><td align="center"
                style="font-size:38px;font-weight:700;color:{_INK};letter-spacing:5px;
                       padding-bottom:28px;font-variant-numeric:tabular-nums;">
          {spaced}
        </td></tr>
        <tr><td align="center" style="font-size:15px;color:{_MUTED};">
          The code is valid for {ttl_minutes} minutes.
        </td></tr>
        <tr><td style="padding-top:28px;border-top:1px solid {_HAIRLINE};
                       margin-top:28px;"></td></tr>
        <tr><td align="center" style="font-size:13px;color:{_MUTED};line-height:1.55;">
          {escape(footer)}
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def confirmation_message(*, to: str, code: str, ttl_minutes: int) -> EmailMessage:
    """Build the address-confirmation message.

    Args:
        to: Recipient address.
        code: The plaintext code. Exists here and in the mail, nowhere else.
        ttl_minutes: How long the code stays valid.

    Returns:
        The rendered message, text and HTML.
    """
    heading = "Your signup confirmation code"
    footer = (
        "If you did not sign up, ignore this email — the account cannot be "
        "confirmed without this code."
    )
    return EmailMessage(
        to=to,
        subject="Signup confirmation code",
        body=(
            f"{heading}\n\n"
            f"    {code}\n\n"
            f"The code is valid for {ttl_minutes} minutes and works once.\n\n"
            f"{footer}\n"
        ),
        html=_shell(heading=heading, code=code, ttl_minutes=ttl_minutes, footer=footer),
    )


def password_reset_message(*, to: str, code: str, ttl_minutes: int) -> EmailMessage:
    """Build the password-reset message.

    Args:
        to: Recipient address.
        code: The plaintext code.
        ttl_minutes: How long the code stays valid.

    Returns:
        The rendered message, text and HTML.
    """
    heading = "Your recovery code"
    footer = (
        "Changing the password signs you out everywhere. If you did not ask "
        "to reset it, no action is needed — but someone entered your address "
        "in the recovery form, so tell us if it keeps happening."
    )
    return EmailMessage(
        to=to,
        subject="Recovery code",
        body=(
            f"{heading}\n\n"
            f"    {code}\n\n"
            f"The code is valid for {ttl_minutes} minutes and works once.\n\n"
            f"{footer}\n"
        ),
        html=_shell(heading=heading, code=code, ttl_minutes=ttl_minutes, footer=footer),
    )


__all__ = ["confirmation_message", "password_reset_message"]
