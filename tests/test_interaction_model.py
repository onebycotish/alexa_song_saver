import json
from pathlib import Path

from lambda_function import HANDLED_INTENTS

MODELS = Path(__file__).resolve().parent.parent / "skill-package" / "interactionModels" / "custom"


def load(locale):
    return json.loads((MODELS / "{}.json".format(locale)).read_text())


def test_locales_are_identical():
    assert load("en-IN") == load("en-US")


def test_handlers_serve_exactly_the_model_intents():
    model_intents = {i["name"] for i in load("en-US")["interactionModel"]["languageModel"]["intents"]}
    assert set(HANDLED_INTENTS) == model_intents


def test_invocation_name_is_song_saver():
    assert load("en-US")["interactionModel"]["languageModel"]["invocationName"] == "song saver"
