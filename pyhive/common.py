"""
Package private common utilities. Do not use directly.
"""

from __future__ import absolute_import
from __future__ import unicode_literals
from pyhive import exc
import abc
import collections
import time


class DBAPICursor(object):
    """Base class for some common DB-API logic"""
    __metaclass__ = abc.ABCMeta

    _STATE_NONE = 0
    _STATE_RUNNING = 1
    _STATE_FINISHED = 2

    def __init__(self, poll_interval=1):
        self._poll_interval = poll_interval
        self._reset_state()

    def _reset_state(self):
        """Reset state about the previous query in preparation for running another query"""
        # State to return as part of DB-API
        self._rownumber = 0

        # Internal helper state
        self._state = self._STATE_NONE
        self._data = collections.deque()
        self._columns = None

    def _fetch_while(self, fn):
        while fn():
            self._fetch_more()
            if fn():
                time.sleep(self._poll_interval)

    @abc.abstractproperty
    def description(self):
        raise NotImplementedError

    def close(self):
        """By default, do nothing"""
        pass

    @abc.abstractmethod
    def _fetch_more(self):
        """Get more results, append it to ``self._data``, and update ``self._state``."""
        raise NotImplementedError

    @property
    def rowcount(self):
        """By default, return -1 to indicate that this is not supported."""
        return -1

    def executemany(self, operation, seq_of_parameters):
        """Prepare a database operation (query or command) and then execute it against all parameter
        sequences or mappings found in the sequence seq_of_parameters.

        Only the final result set is retained.

        Return values are not defined.
        """
        for parameters in seq_of_parameters[:-1]:
            self.execute(operation, parameters)
            while self._state != self._STATE_FINISHED:
                self._fetch_more()
        if seq_of_parameters:
            self.execute(operation, seq_of_parameters[-1])

    def fetchone(self):
        """Fetch the next row of a query result set, returning a single sequence, or None when no
        more data is available.

        An Error (or subclass) exception is raised if the previous call to execute() did not
        produce any result set or no call was issued yet.
        """
        if self._state == self._STATE_NONE:
            raise exc.ProgrammingError("No query yet")

        # Sleep until we're done or we have some data to return
        self._fetch_while(lambda: not self._data and self._state != self._STATE_FINISHED)

        if not self._data:
            return None
        else:
            self._rownumber += 1
            return self._data.popleft()

    def fetchmany(self, size=None):
        """Fetch the next set of rows of a query result, returning a sequence of sequences (e.g. a
        list of tuples). An empty sequence is returned when no more rows are available.

        The number of rows to fetch per call is specified by the parameter. If it is not given, the
        cursor's arraysize determines the number of rows to be fetched. The method should try to
        fetch as many rows as indicated by the size parameter. If this is not possible due to the
        specified number of rows not being available, fewer rows may be returned.

        An Error (or subclass) exception is raised if the previous call to .execute*() did not
        produce any result set or no call was issued yet.
        """
        if size is None:
            size = self.arraysize
        result = []
        for _ in xrange(size):
            one = self.fetchone()
            if one is None:
                break
            else:
                result.append(one)
        return result

    def fetchall(self):
        """Fetch all (remaining) rows of a query result, returning them as a sequence of sequences
        (e.g. a list of tuples).

        An Error (or subclass) exception is raised if the previous call to .execute*() did not
        produce any result set or no call was issued yet.
        """
        result = []
        while True:
            one = self.fetchone()
            if one is None:
                break
            else:
                result.append(one)
        return result

    @property
    def arraysize(self):
        """This read/write attribute specifies the number of rows to fetch at a time with
        ``.fetchmany()``. It defaults to 1 meaning to fetch a single row at a time.
        """
        return self._arraysize

    @arraysize.setter
    def arraysize(self, value):
        self._arraysize = value

    def setinputsizes(self, sizes):
        """Does nothing by default"""
        pass

    def setoutputsize(self, size, column=None):
        """Does nothing by default"""
        pass

    #
    # Optional DB API Extensions
    #

    @property
    def rownumber(self):
        """This read-only attribute should provide the current 0-based index of the cursor in the
        result set.

        The index can be seen as index of the cursor in a sequence (the result set). The next fetch
        operation will fetch the row indexed by .rownumber in that sequence.
        """
        return self._rownumber

    def next(self):
        """Return the next row from the currently executing SQL statement using the same semantics
        as ``.fetchone()``. A StopIteration exception is raised when the result set is exhausted.
        """
        one = self.fetchone()
        if one is None:
            raise StopIteration
        else:
            return one

    def __iter__(self):
        """Return self to make cursors compatible to the iteration protocol."""
        return self


class DBAPITypeObject(object):
    # Taken from http://www.python.org/dev/peps/pep-0249/#implementation-hints
    def __init__(self, *values):
        self.values = values

    def __cmp__(self, other):
        if other in self.values:
            return 0
        if other < self.values:
            return 1
        else:
            return -1


class ParamEscaper(object):
    def escape_args(self, parameters):
        if isinstance(parameters, dict):
            return {k: self.escape_item(v) for k, v in parameters.iteritems()}
        elif isinstance(parameters, (list, tuple)):
            return tuple(self.escape_item(x) for x in parameters)
        else:
            raise exc.ProgrammingError("Unsupported param format: {}".format(parameters))

    def escape_number(self, item):
        return item

    def escape_string(self, item):
        # This is good enough when backslashes are literal, newlines are just followed, and the way
        # to escape a single quote is to put two single quotes.
        # (i.e. only special character is single quote)
        return "'{}'".format(item.replace("'", "''"))

    def escape_item(self, item):
        if isinstance(item, (int, long, float)):
            return self.escape_number(item)
        elif isinstance(item, basestring):
            return self.escape_string(item)
        else:
            raise exc.ProgrammingError("Unsupported object {}".format(item))
