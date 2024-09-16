from typing import Optional
from os import makedirs
import logging
import traceback
import json
from logging import Logger
from telegram import Update, BotCommand, BotCommandScopeChat
from telegram.ext import Application, CommandHandler, MessageHandler, PicklePersistence, CallbackContext, filters
import telegram.error


"""Command description decorator."""
def command_description(description: str):
    def _(f):
        f.description = description
        return f
    return _


"""TelegramBot class defines the basing class for the Bot."""
class TelegramBot:
    _logger: Logger
    __user_id: int
    __types = [
        "_command_handler",
        "_message_handler"
    ]
    application: Application

    def __init__(self, logger: Logger, token: str, user_id: int):
        self._logger = logger
        self.__user_id = int(user_id)

        # Store persistent data
        makedirs('.data', exist_ok=True)  # Create data
        persistence = PicklePersistence(filepath='.data/persistence')

        # Create an application
        self.application = Application.builder().token(token).persistence(persistence).post_init(self._post_init).build()
        self.__add_dispatchers()
        self.application.add_error_handler(self._error_handler)

    async def _post_init(self, application: Application):
        commands = []
        handler_functions = list(filter(lambda x: x.endswith("_command_handler"), dir(self)))
        for handler in handler_functions:
            attr = getattr(self, handler)
            commands += [BotCommand(handler.replace('_command_handler', ''), attr.description)]

        try:
            await application.bot.set_my_commands(commands, scope=BotCommandScopeChat(self.__user_id))
        except telegram.error.BadRequest as exc:
            self._logger.warning(f"Can't set my commands for the bot: {exc.message}")

    def _log(self, update: Update, level: str, message: str) -> None:
        """Log message with chat_id and message_id."""
        _level = getattr(logging, level.upper())
        self._logger.log(_level, f'[{update.effective_chat.id}:{update.effective_message.message_id}] {message}')

    async def _deny_access(self, update: Update, context: CallbackContext) -> None:
        """Deny unauthorized access"""
        self._log(update, 'info',
                     f'Access denied to {update.effective_user.full_name} (@{update.effective_user.username}),'
                     f' userId {update.effective_user.id}')
        await update.effective_message.reply_text(
            f'Access denied. Your ID ({update.effective_user.id}) is not whitelisted')

    def __add_dispatchers(self):
        self.application.add_handler(MessageHandler(~filters.Chat(self.__user_id), self._deny_access))
        for _type in self.__types:
            handler_functions = list(filter(lambda x: x.endswith(_type), dir(self)))
            for handler in handler_functions:
                if _type == '_message_handler':
                    self.application.add_handler(
                        MessageHandler(
                            filters.TEXT & ~filters.COMMAND & filters.Chat(self.__user_id),
                            getattr(self, handler)
                        )
                    )
                elif _type == '_command_handler':
                    setattr(self, handler, getattr(self, handler))
                    self.application.add_handler(
                        CommandHandler(
                            handler.replace(_type, ''),
                            getattr(self, handler),
                            filters.Chat(self.__user_id)
                        )
                    )

    async def _error_handler(self, update: Optional[object], context: CallbackContext) -> None:
        """Log the error and send a telegram message to notify the developer."""
        if isinstance(context.error, telegram.error.Forbidden):
            return

        if isinstance(context.error, telegram.error.Conflict):
            self._logger.error('Telegram requests conflict')
            return
        # Log the error before we do anything else, so we can see it even if something breaks.
        self._logger.error(msg='Exception while handling an update: ', exc_info=context.error)

        # If there is no update, don't send an error report (probably a network error, happens sometimes)
        if update is None:
            return

        # Build the message with some markup and additional information about what happened.
        update_str = update.to_dict() if isinstance(update, Update) else str(update)
        # traceback.format_exception returns the usual python message about an exception, but as a
        # list of strings rather than a single string, so we have to join them together.
        tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
        tb_string = ''.join(tb_list)
        message = (
            f'update = {json.dumps(update_str, indent=2, ensure_ascii=False)}'
            '\n\n'
            f'context.chat_data = {str(context.chat_data)}\n\n'
            f'context.user_data = {str(context.user_data)}\n\n'
            f'{tb_string}'
        )

        # Finally, send the message
        self._logger.info('Sending error report')
        await context.bot.send_document(
            chat_id=self.__user_id, document=message, filename='error_report.txt',
            caption='#error_report\nAn exception was raised in runtime\n'
        )

        if update:
            error_class_name = ".".join([context.error.__class__.__module__, context.error.__class__.__qualname__])
            await update.effective_message.reply_text(f'Error\n{error_class_name}: {str(context.error)}')

    def run_polling(self):
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)
