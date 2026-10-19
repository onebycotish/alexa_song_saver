"""Builders for real Alexa request envelopes, fed to the skill's entry point."""


def _envelope(request):
    ids = {"application": {"applicationId": "amzn1.ask.skill.test"}, "user": {"userId": "amzn1.ask.account.test"}}
    return {
        "version": "1.0",
        "session": dict(ids, new=True, sessionId="amzn1.echo-api.session.test"),
        "context": {
            "System": dict(
                ids,
                device={"deviceId": "amzn1.ask.device.test", "supportedInterfaces": {}},
                apiEndpoint="https://api.amazonalexa.com",
            )
        },
        "request": dict(request, requestId="amzn1.echo-api.request.test", timestamp="2026-10-19T00:00:00Z", locale="en-US"),
    }


def launch():
    return _envelope({"type": "LaunchRequest"})


def intent(name):
    return _envelope({"type": "IntentRequest", "intent": {"name": name, "confirmationStatus": "NONE"}})


def session_ended():
    return _envelope({"type": "SessionEndedRequest", "reason": "USER_INITIATED"})
