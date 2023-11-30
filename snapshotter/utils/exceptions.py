import json


class SelfExitException(
    Exception,
):
    """
    Exception used by process hub core to signal core exit.
    """
    pass


class GenericExitOnSignal(Exception):
    """Exception to be used whenever any other launched process/callback worker receives a signal to 'exit' - [INT, TERM, QUIT]"""
    pass


class RPCException(Exception):
    def __init__(self, request, response, underlying_exception, extra_info):
        """
        Initializes a new instance of the ApiException class.

        :param request: The request that caused the exception.
        :type request: Any
        :param response: The response received from the server.
        :type response: Any
        :param underlying_exception: The underlying exception that caused this exception.
        :type underlying_exception: Exception
        :param extra_info: Additional information about the exception.
        :type extra_info: Any
        """
        self.request = request
        self.response = response
        self.underlying_exception: Exception = underlying_exception
        self.extra_info = extra_info

    def __str__(self):
        """Return a JSON string representation of the exception object."""
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
        """
        Return a string representation of the exception.
        """
        return self.__str__()
