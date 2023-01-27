class SelfExitException(Exception):  # used by process hub core to signal core exit
    pass


class GenericExitOnSignal(Exception):
    # to be used whenever any other launched process/callback worker receives a signal to 'exit' - [INT, TERM, QUIT]
    pass
