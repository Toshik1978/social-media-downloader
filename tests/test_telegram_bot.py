from bot.telegram_bot import command_description


def test_command_description_sets_attribute():
    @command_description("Do the thing")
    def handler():
        return "ok"

    assert handler.description == "Do the thing"
    assert handler() == "ok"
