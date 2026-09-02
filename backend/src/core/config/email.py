"""Outbound email: the transport, and the two flows that need one (P1.6).

This service could not send mail at all until this existed. Invitations and
activation codes are handed over out of band — the response carries the token
once and a human passes it on — which works because somebody is always already
in the conversation. Password reset is the first flow where nobody is: the
person who needs it is, by definition, the one we cannot reach.

**Everything here is off by default, and that is load-bearing.** A half-wired
mail path is worse than none: the failure mode of "confirmation required, mail
not actually sending" is that nobody can finish signing up and the symptom
appears at the registration form rather than at the thing that is broken. So
the flags default off, and `assembly.py` refuses to boot a configuration that
demands mail it cannot send.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class EmailSettings(BaseSettings):
    """SMTP transport and the verification-code policy."""

    # --- Transport ---
    # OFF means the transport is the logging one: a message is rendered and
    # written to the application log instead of being sent. That is the right
    # default for local and CI — the code is visible to whoever is testing, no
    # network is touched, and no test can accidentally mail a real address.
    email_enabled: bool = Field(default=False)
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str = Field(default="")
    smtp_password: str = Field(default="")
    # STARTTLS on 587 is the common shape; set false only for a local relay that
    # is already on a trusted network. Plaintext SMTP over the internet hands
    # every reset code to anyone on the path.
    smtp_use_tls: bool = Field(default=True)
    #: The From: address. Must be on a domain whose SPF/DKIM authorise this
    #: sender, or the mail is delivered to spam and the feature silently fails
    #: for the users least able to diagnose it.
    email_from: str = Field(default="")
    email_from_name: str = Field(default="Marketplace Analytics")
    #: Whole-operation budget per message. Sending happens inside the request,
    #: so a hung relay must not become a hung signup form.
    smtp_timeout_seconds: float = Field(default=10.0, gt=0)

    # --- Flows ---
    # When true, an unconfirmed address cannot redeem an activation code or
    # accept an invitation — the two moments an address stops being decorative
    # and starts deciding who is in a company. Deliberately NOT a login gate:
    # see `require_confirmed_email` for why the login answer stays uniform.
    email_confirmation_required: bool = Field(default=False)
    # Password reset is independent of the above: it needs a transport, not a
    # confirmed address. Proving control of the mailbox now is what the reset
    # *is*, so demanding a prior confirmation would only lock out the accounts
    # that most need it.
    password_reset_enabled: bool = Field(default=False)

    # --- Verification codes ---
    # Twenty minutes: long enough for mail to arrive and a person to switch
    # windows, short enough that a code read over someone's shoulder is
    # usually already dead. The wording in the mail is generated from this
    # value, so the two cannot drift apart.
    verification_code_ttl_seconds: int = Field(default=1200, ge=60)
    # Six digits is a million possibilities, which is only safe because this cap
    # exists. Five wrong guesses kills the row and a new code must be requested.
    verification_code_max_attempts: int = Field(default=5, ge=1)
    # Digits, not letters: it is retyped from a mail client, often on a phone,
    # and letters invite the O/0 and l/1 confusion that turns into support.
    verification_code_length: int = Field(default=6, ge=6, le=10)
