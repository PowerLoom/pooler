import json


class SelfExitException(
    Exception,
):  # used by process hub core to signal core exit
    pass


class GenericExitOnSignal(Exception):
    # to be used whenever any other launched process/callback worker receives a signal to 'exit' - [INT, TERM, QUIT]
    pass


class RPCException(Exception):
    def __init__(self, request, response, underlying_exception, extra_info):
        self.request = request
        self.response = response
        self.underlying_exception: Exception = underlying_exception
        self.extra_info = extra_info

    def __str__(self):
        ret = {
            'request': self.request,
            'response': self.response,
            'extra_info': self.extra_info,
            'exception': None,
        }
        if isinstance(self.underlying_exception, Exception):
            ret.update({'exception': self.underlying_exception.__str__()})
        return json.dumps(ret)

    def __repr__(self):
        return self.__str__()
