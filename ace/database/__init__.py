# vim: sw=4:ts=4:et:cc=120

import datetime
import functools
import json
import logging
import os
import os.path
import random
import re
import sys
import threading
import time
import uuid
import warnings

from contextlib import closing, contextmanager
from typing import Set
from urllib.parse import urlsplit

import ace
import ace.analysis
import ace.constants

from ace.analysis import RootAnalysis, Indicator, IndicatorList
from ace.constants import *

# from ace.error import report_exception

from sqlalchemy import (
    BigInteger,
    Column,
    DATE,
    DATETIME,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    TIMESTAMP,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    exc,
    func,
    text,
)

# XXX get rid of these
from sqlalchemy.dialects.mysql import BOOLEAN, VARBINARY, BLOB

from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker, relationship, reconstructor, backref, validates, scoped_session, aliased
from sqlalchemy.orm.exc import NoResultFound, DetachedInstanceError
from sqlalchemy.sql.expression import Executable
from sqlalchemy.orm.session import Session
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import and_, or_
from sqlalchemy.ext.hybrid import hybrid_property, hybrid_method

DatabaseSession = None
Base = declarative_base()
engine = None


def get_session():
    return DatabaseSession


@contextmanager
def get_db_connection():
    try:
        connection = engine.connect()
        # return the raw db api connection object
        yield connection.connection
    finally:
        connection.close()


def use_db(method=None):
    """Utility decorator to pass an opened database connection and cursor object as keyword
    parameters db and c respectively. Execute is wrapped in a try/catch for database errors.
    Returns None on error and logs error message and stack trace."""

    if method is None:
        return functools.partial(use_db)

    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        try:
            with get_db_connection() as db:
                c = db.cursor()
                return method(db=db, c=c, *args, **kwargs)
        except DBAPIError as e:
            logging.error("database error: {}".format(e))
            et, ei, tb = sys.exc_info()
            raise e.with_traceback(tb)

    return wrapper


def execute_with_retry(db, cursor, sql_or_func, params=(), attempts=3, commit=False):
    """Executes the given SQL or function (and params) against the given cursor with
    re-attempts up to N times (defaults to 2) on deadlock detection.

    If sql_or_func is a callable then the function will be called as
    sql_or_func(db, cursor, *params).

    To execute a single statement, sql is the parameterized SQL statement
    and params is the tuple of parameter values.  params is optional and defaults
    to an empty tuple.

    To execute multi-statement transactions, sql is a list of parameterized
    SQL statements, and params is a matching list of tuples of parameters.

    Returns the rowcount for a single statement, or a list of rowcount for multiple statements,
    or the result of the function call."""

    assert callable(sql_or_func) or isinstance(sql_or_func, str) or isinstance(sql_or_func, list)
    assert (
        params is None
        or isinstance(params, tuple)
        or (isinstance(params, list) and all([isinstance(_, tuple) for _ in params]))
    )

    # if we are executing sql then make sure we have a list of SQL statements and a matching list
    # of tuple parameters
    if not callable(sql_or_func):
        if isinstance(sql_or_func, str):
            sql_or_func = [sql_or_func]

        if isinstance(params, tuple):
            params = [params]
        elif params is None:
            params = [() for _ in sql_or_func]

        if len(sql_or_func) != len(params):
            raise ValueError(
                "the length of sql statements does not match the length of parameter tuples: {} {}".format(
                    sql_or_func, params
                )
            )
    count = 1
    while True:
        try:
            results = []
            if callable(sql_or_func):
                results.append(sql_or_func(db, cursor, *params))
            else:
                for (_sql, _params) in zip(sql_or_func, params):
                    # if ace.CONFIG['global'].getboolean('log_sql'):
                    # logging.debug(f"executing with retry (attempt #{count}) sql {_sql} with paramters {_params}")
                    cursor.execute(_sql, _params)
                    results.append(cursor.rowcount)

            if commit:
                db.commit()

            if len(results) == 1:
                return results[0]

            return results

        except DBAPIError as e:
            # see http://stackoverflow.com/questions/25026244/how-to-get-the-mysql-type-of-error-with-pymysql
            # to explain e.args[0]
            if (e.args[0] == 1213 or e.args[0] == 1205) and count < attempts:
                logging.warning("deadlock detected -- trying again (attempt #{})".format(count))
                try:
                    db.rollback()
                except Exception as rollback_error:
                    logging.error("rollback failed for transaction in deadlock: {}".format(rollback_error))
                    raise e

                count += 1
                time.sleep(random.uniform(0, 1))
                continue
            else:
                if not callable(sql_or_func):
                    i = 0
                    for _sql, _params in zip(sql_or_func, params):
                        logging.warning(
                            "DEADLOCK STATEMENT #{} SQL {} PARAMS {}".format(
                                i, _sql, ",".join([str(_) for _ in _params])
                            )
                        )
                        i += 1

                    # TODO log innodb lock status
                    raise e


# new school database connections
# from flask_login import UserMixin
# from werkzeug.security import generate_password_hash, check_password_hash

# if target is an executable, then *args is to session.execute function
# if target is a callable, then *args is to the callable function (whatever that is)


def retry_on_deadlock(targets, *args, attempts=2, commit=False, **kwargs):
    """Executes the given targets, in order. If a deadlock condition is detected, the database session
    is rolled back and the targets are executed in order, again. This can happen up to :param:attempts times
    before the failure is raised as an exception.

    :param targets Can be any of the following
    * A callable.
    * A list of callables.
    * A sqlalchemy.sql.expression.Executable object.
    * A list of sqlalchemy.sql.expression.Executable objects.
    :param int attempts The maximum number of times the operations are tried before passing the exception on.
    :param bool commit If set to True then the ``commit`` function is called on the session object before returning
    from the function. If a deadlock occurs during the commit then further attempts are made.

    In the case where targets are functions, session can be omitted, in which case :meth:ace.db is used to
    acquire a Session to use. When this is the case, the acquired Session object is passed as a keyword parameter
    to the functions.

    In the case where targets are executables, session cannot be omitted. The executables are passed to the
    ``execute`` function of the Session object as if you had called ``session.execute(target)``.

    :return This function returns the last operation in the list of targets."""

    if not isinstance(targets, list):
        targets = [targets]

    current_attempt = 0
    while True:
        try:
            last_result = None
            for target in targets:
                if isinstance(target, Executable) or isinstance(target, str):
                    ace.db.execute(target, *args, **kwargs)
                elif callable(target):
                    last_result = target(*args, **kwargs)

            if commit:
                ace.db.commit()

            return last_result

        except DBAPIError as e:
            # catch the deadlock error ids 1213 and 1205
            # NOTE this is for MySQL only
            if e.orig.args[0] == 1213 or e.orig.args[0] == 1205 and current_attempt < attempts:
                logging.debug(f"DEADLOCK STATEMENT attempt #{current_attempt + 1} SQL {e.statement} PARAMS {e.params}")

                try:
                    ace.db.rollback()  # rolls back to the begin_nested()
                except Exception as e:
                    logging.error(f"unable to roll back transaction: {e}")

                    et, ei, tb = sys.exc_info()
                    raise e.with_traceback(tb)

                # ... and try again
                time.sleep(0.1)  # ... after a bit
                current_attempt += 1
                continue

            # otherwise we propagate the error
            et, ei, tb = sys.exc_info()
            raise e.with_traceback(tb)


def retry_function_on_deadlock(function, *args, **kwargs):
    assert callable(function)
    return retry_on_deadlock(function, *args, **kwargs)


def retry_sql_on_deadlock(executable, *args, **kwargs):
    assert isinstance(executable, Executable)
    return retry_on_deadlock(executable, *args, **kwargs)


def retry_multi_sql_on_deadlock(executables, *args, **kwargs):
    assert isinstance(executables, list)
    assert all([isinstance(_, Executable) for _ in executables])
    return retry_on_deadlock(executables, *args, **kwargs)


def retry(_func, *args, **kwargs):
    """Executes the wrapped function with retry_on_deadlock."""

    @functools.wraps(_func)
    def wrapper(*w_args, **w_kwargs):
        w_kwargs.update(kwargs)
        return retry_function_on_deadlock(_func, *w_args, **w_kwargs)

    return wrapper


def initialize_database():
    """Initializes database connections by creating the SQLAlchemy engine and session objects."""

    global DatabaseSession, engine
    # from config import config, get_sqlalchemy_database_uri, get_sqlalchemy_database_options

    # see https://github.com/PyMySQL/PyMySQL/issues/644
    # /usr/local/lib/python3.6/dist-packages/pymysql/cursors.py:170: Warning: (1300, "Invalid utf8mb4 character string: '800363'")
    warnings.filterwarnings(action="ignore", message=".*Invalid utf8mb4 character string.*")

    import ace

    # engine = create_engine(
    # get_sqlalchemy_database_uri('ace'),
    # **get_sqlalchemy_database_options('ace'))

    # TODO get this from configuration?
    if os.path.exists("ace.db"):
        os.remove("ace.db")
    engine = create_engine("sqlite:///ace.db")

    # running this out of memory does not work due to the multithreading
    # each connection gets its own thread (thanks to session scoping)
    # and this in-memory db only exists for the connection its on
    # engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def connect(dbapi_connection, connection_record):
        pid = os.getpid()
        tid = threading.get_ident()
        connection_record.info["pid"] = pid
        connection_record.info["tid"] = tid

        # XXX check for sqlite
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(engine, "checkout")
    def checkout(dbapi_connection, connection_record, connection_proxy):
        pid = os.getpid()
        if connection_record.info["pid"] != pid:
            connection_record.connection = connection_proxy.connection = None
            message = (
                f"connection record belongs to pid {connection_record.info['pid']} attempting to check out in pid {pid}"
            )
            logging.debug(message)
            raise exc.DisconnectionError(message)

        tid = threading.get_ident()
        if connection_record.info["tid"] != tid:
            connection_record.connection = connection_proxy.connection = None
            message = (
                f"connection record belongs to tid {connection_record.info['tid']} attempting to check out in tid {tid}"
            )
            logging.debug(message)
            raise exc.DisconnectionError(message)

    DatabaseSession = sessionmaker(bind=engine)
    ace.db = scoped_session(DatabaseSession)
