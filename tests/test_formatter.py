from localflow.config import AppProfile, Config
from localflow.formatter import FormatContext, format_transcript


def make_config(**overrides) -> Config:
    config = Config()
    config.dictionary = overrides.pop("dictionary", {})
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def test_removes_fillers():
    config = make_config()
    assert format_transcript("Um, I think, uh, we should ship it.", config) == "I think, we should ship it."


def test_keeps_meaningful_words():
    config = make_config()
    out = format_transcript("I would like to summon the courage.", config)
    assert "like" in out and "summon" in out


def test_spoken_commands():
    config = make_config()
    out = format_transcript("First point. New line. Second point.", config)
    assert out == "First point.\nSecond point."


def test_new_paragraph():
    config = make_config()
    out = format_transcript("Intro new paragraph body text.", config)
    assert out == "Intro\n\nBody text."


def test_dictionary_replacement():
    config = make_config(dictionary={"something new": "Something New"})
    out = format_transcript("The something new team shipped it.", config)
    assert "Something New" in out


def test_hallucination_filtered():
    config = make_config()
    assert format_transcript("Thank you.", config) == ""
    assert format_transcript(" ", config) == ""


def test_casual_profile_drops_trailing_period():
    config = make_config()
    ctx = FormatContext(bundle_id="com.tinyspeck.slackmacgap", profile=AppProfile(casual=True))
    assert format_transcript("sounds good to me.", config, ctx) == "Sounds good to me"


def test_casual_profile_keeps_multi_sentence():
    config = make_config()
    ctx = FormatContext(profile=AppProfile(casual=True))
    out = format_transcript("First thing. Second thing.", config, ctx)
    assert out.endswith(".")


def test_capitalizes_sentences():
    config = make_config()
    out = format_transcript("first thing. second thing.", config)
    assert out == "First thing. Second thing."


def test_commands_disabled():
    config = make_config(spoken_commands=False)
    out = format_transcript("First point new line second point.", config)
    assert "\n" not in out


def test_spoken_punctuation():
    config = make_config()
    assert format_transcript("Are you coming question mark", config) == "Are you coming?"
    assert format_transcript("That's amazing exclamation mark", config) == "That's amazing!"
    assert format_transcript("Send it today full stop", config) == "Send it today."


def test_bullet_points():
    config = make_config()
    out = format_transcript("We need bullet point creative bullet point offer.", config)
    assert out == "We need\n- Creative\n- Offer."
