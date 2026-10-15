"""Stage 2 - the natural-language command.

For now the command is typed. This stage exists as its own module so that the input
can later come from somewhere else - the contextual ASR, a microphone, a file of test
instructions - without any other stage noticing: it only has to put a string into
``payload['command']``.
"""

import time

from core.pipeline import Stage, StageError, StageStatus


class CommandStage(Stage):
    """Take the typed command, check it is usable and record it."""

    name = 'command'
    title = 'Command'
    description = 'The natural-language command, as the user typed it.'

    def execute(self, context, payload):
        command = (payload.get('command') or '').strip()
        if not command:
            raise StageError('The command is empty — type what the robot should do.')

        payload['command'] = command
        payload['t_command'] = time.time()   # the clock the loop's timestamps run on
        self.log.info('command: %s', command)

        words = len(command.split())
        artifacts = {'command': context.write_text('command.txt', command)}

        # Not an error, but worth seeing in the log: a very short command is usually
        # missing an operand and will be rejected by the generator's Rule U.
        if words < 3:
            self.log.warning('the command is only %d words long — the generator may '
                             'reject it as unclear', words)

        return self.result(
            StageStatus.PASSED,
            summary=f'{words} words, {len(command)} characters',
            detail={'command': command, 'words': words, 'characters': len(command)},
            artifacts=artifacts)
