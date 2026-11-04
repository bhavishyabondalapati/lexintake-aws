"""Two kinds of failure. Step Functions matches on the exception's class name (the "Error" of a
failed Lambda task), so these names are used in the state machine's Retry/Catch blocks.

- TransientError: worth trying again (rate limit, timeout, API overloaded). The state machine
  retries with exponential backoff.
- PermanentError: retrying will not help (corrupt PDF, file too large, bad request). The state
  machine does not retry; it sends the document to the dead-letter queue.
"""


class TransientError(Exception):
    pass


class PermanentError(Exception):
    pass
