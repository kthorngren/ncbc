#import threading
import time
import re
import copy
import sys

import pymysql.cursors
from warnings import filterwarnings
from warnings import resetwarnings

from pymysql.err import ProgrammingError, DataError, IntegrityError, NotSupportedError, OperationalError

from MySql import local_host



"""
https://stackoverflow.com/questions/1210458/how-can-i-generate-a-unique-id-in-python
"""
import threading
def gen_uid():
    _uid = threading.local()
    if getattr(_uid, "uid", None) is None:
        _uid.tid = threading.current_thread().ident
        _uid.uid = 0
    _uid.uid += 1
    return (_uid.tid, _uid.uid)



# create logger
import logging
import os
LEVEL = logging.INFO
logger = logging.getLogger(os.path.basename(__file__).split('.')[0] if __name__ == '__main__' else __name__)
logger.setLevel(LEVEL)

# create console handler and set level to debug
ch = logging.StreamHandler()
ch.setLevel(LEVEL)

# create formatter
formatter = logging.Formatter('%(asctime)s.%(msecs)03d: %(levelname)s: %(name)s.%(funcName)s(): %(message)s', datefmt='%m-%d-%Y %H:%M:%S')

# add formatter to ch
ch.setFormatter(formatter)

# add ch to logger
logger.addHandler(ch)
# end create logger

#global lock variable
#_lock = threading.Lock()
#print(_lock)

TEST_CASE = '** '

def escape_sql(data):
    """
    Escape the " that might be in a string before creating sql string
    :param data: dictionary or string to escape "
    :return: updated data
    """

    if type(data) == type({}):
        for k, v in data.items():
            if '"' in v:
                data[k] = v.replace('"', r'\"')
    elif type(data) == type(' '):
        data = data.replace('"', r'\"')

    return data


class LockableMysqlConnection:
    def __init__(self, host, user, password, db):
        logger.debug('LockableMysqlConnection.__init__()')
        self.host = host
        self.user = user
        self.password = password
        self.db = db
        self.lock = threading.Lock()
        self.connect()
        self.cursor = None

    def __enter__(self):
        logger.debug('LockableMysqlConnection.__enter__()')
        if self.connection:
            self.lock.acquire()
            logger.debug('LockableMysqlConnection.__enter__() - lock.acquire result: {}'.format(self.lock.locked()))
            self.cursor = self.connection.cursor()
            logger.debug('LockableMysqlConnection.__enter__() - cursor created')
        else:
            logger.error('LockableMysqlConnection.__enter__() - self.connection is None')
            self.cursor = None
        return self

    def __exit__(self, type, value, traceback):
        logger.debug('LockableMysqlConnection.__exit__()')
        if self.cursor:
            try:
                self.connection.commit()
                logger.debug('LockableMysqlConnection.__exit__() - commit')
            except Exception as e:
                logger.error('LockableMysqlConnection.__exit__() - Unable to execute "self.connection.commit()", error: {}'.format(e))
                raise
        if self.cursor is not None:
            self.cursor.close()
            self.cursor = None
            logger.debug('LockableMysqlConnection.__exit__() - cursor closed')
        else:
            logger.error('LockableMysqlConnection.__exit__() - cursor does not exist')
        if self.lock.locked():
            self.lock.release()
            logger.debug('LockableMysqlConnection.__exit__() - lock released')
        else:
            logger.error('LockableMysqlConnection.__exit__() - not locked')
        if self.connection:
            logger.debug('LockableMysqlConnection.__exit__() - Closing connection')
            self.disconnect()
        else:
            logger.error('LockableMysqlConnection.__exit__() - No connection to close')

    def close_cursor(self):
        if self.cursor is not None:
            self.cursor.close()
            self.cursor = None
            logger.debug('LockableMysqlConnection.close_cursor() - cursor close')
        else:
            logger.debug('LockableMysqlConnection.close_cursor() - cursor does not exist')
        if self.lock.locked():
            self.lock.release()
            logger.debug('LockableMysqlConnection.close_cursor() - lock released')
        else:
            logger.debug('LockableMysqlConnection.close_cursor() - not locked')

    def configure_connection(self, host, user, password, db):
        self.host = host
        self.user = user
        self.password = password
        self.db = db


    def connect(self):
        logger.debug('LockableMysqlConnection.connect() - Creating connection')
        try:
            self.connection = pymysql.connect(host=self.host,
                                              user=self.user,
                                              password=self.password,
                                              db=self.db,
                                              cursorclass=pymysql.cursors.DictCursor)
            logger.debug('LockableMysqlConnection.connect() - Connection successfull')
        except OperationalError as e:
            logger.error('LockableMysqlConnection.connect() - error connecting to server: {}, error: {}'.format(self.host, e))
            self.connection = None


    def disconnect(self):
        if self.cursor:
            self.close_cursor()
        if self.connection:
            logger.debug('LockableMysqlConnection.disconnect() - closing connection')
        else:
            logger.debug('LockableMysqlConnection.disconnect() - no connection to close')
        #self.connection = None

class Database:

    def __init__(self, host, user, password, db):
        logger.debug('Init')
        self.host = host
        self.user = user
        self.password = password
        self.db = db
        self.mysql = LockableMysqlConnection(host, user, password, db)
        self.result = {}
        self.connected = None
        self.error = ''
        self.status = ''
        self.sql = ''
        self.validated = False
        self.validation_error = ''
        self.cursorclass = pymysql.cursors.DictCursor
        self.cursor = None
        self.results = {}

    def connect(self, reconnect=False):
        if self.mysql.connection:
            if reconnect:
                logger.debug('Closing existing connection, reconnect: {}'.format(reconnect))
                self.disconnect()
            else:
                logger.debug('Skipping closing existing connection, reconnect: {}'.format(reconnect))
                return
        logger.debug('Creating new LockableMysqlConnection')
        self.mysql.connect()
        if self.mysql.connection:
            logger.debug('Creating new connection - successful')
        else:
            logger.debug('Creating new connection - failed')


    def disconnect(self):
        self.mysql.disconnect()
        self.connection = None

    def set_status(self, status='success', error=''):
        logger.debug('Setting status: {}'.format(status))
        logger.debug('Setting error: {}'.format(error))
        self.status = status
        self.error = error
        if error:
            logger.debug('Setting cursor to None due to error')
            self.cursor = None  #if error clear the cursor to keep from getting results from previous query
            self.mysql.close_cursor()

    def get_result(self):
        return self.status

    def get_error(self):
        return self.error

    def sql_query(self, sql, uid=''):
        logger.debug('sql_query() - {}'.format(sql))
        #print(sql)
        get_context = False
        #print('sql_query uid', uid)
        with self.mysql:
            logger.debug('Using self.mysql context: {}'.format(self.mysql))
            get_context = True
            self.sql_error = ''
            logger.debug('Using cursor object: {}'.format(self.mysql.cursor))
            try:
                self.mysql.connection.ping(True)   #re-establish connnection if needed
            except Exception as e:
                self.sql_error = str(e)
                self.set_status(status='error', error=self.sql_error)
                logger.error('Unable to ping mysql server: {}'.format(e))
                #self.mysql.close_cursor()  # make sure to clear cursor and remove lock
                self.results = {}  # clear out any remaininig SQL responses
                return self
            try:
                if 'insert' and 'ignore' in sql.lower():   #suppress "Duplicate entry '<value>' for key 'name_UNIQUE'" warning
                    filterwarnings('ignore', category = self.mysql.cursor.Warning)
                    self.mysql.cursor.execute(sql)
                    resetwarnings()
                else:
                    self.mysql.cursor.execute(sql)
            except Exception as e:
                self.sql_error = str(e)
                self.set_status(status='error', error=self.sql_error)
                logger.warning('sql_execute() error: {}'.format(e))
                logger.warning('  sql: {}'.format(sql))
                #self.mysql.close_cursor()  # make sure to clear cursor and remove lock
                self.results = {}  # clear out any remaininig SQL responses
            else:
                self.cursor = copy.copy(self.mysql.cursor)
                logger.debug('Saving cursor object: {}'.format(self.cursor))
                if uid:
                    logger.debug('UID: {}, fetching all records'.format(self.cursor))
                    self.results[uid] = self.fetchall()
                    #print(self.results)
                self.set_status()

                if 'insert' in sql.lower() or 'update' in sql.lower() or 'delete' in sql.lower():
                    #self.connection.commit()
                    logger.debug('Rows affected: {}'.format(self.row_count()))
                else:
                    logger.debug('Rows returned: {}'.format(self.row_count()))
                if self.sql_error:
                    logger.error('Rows returned: {} for error: "{}"sql:\n{}'.format(self.row_count(), self.sql_error, sql))


        if get_context == False:
            logger.error('Unable to get with context for sql: {}'.format(sql))
        return self

    def sql_execute(self, sql):
        logger.debug('sql_execute() - {}'.format(sql))
        self.sql_error = ''

        try:
            if 'insert' and 'ignore' in sql.lower():   #suppress "Duplicate entry '<value>' for key 'name_UNIQUE'" warning
                filterwarnings('ignore', category = self.mysql.cursor.Warning)
                self.mysql.cursor.execute(sql)
                resetwarnings()
            else:
                self.mysql.cursor.execute(sql)
            self.set_status()

            if 'insert' in sql.lower() or 'update' in sql.lower() or 'delete' in sql.lower():
                #self.connection.commit()
                logger.debug('Rows affected: {}'.format(self.row_count()))
            else:
                logger.debug('Rows returned: {}'.format(self.row_count()))

        except Exception as e:
            self.sql_error = str(e)
            self.set_status(status='error', error=self.sql_error)
            logger.warning('sql_execute() error: {}'.format(e))


    def one(self, uid):

        result = self.results.pop(uid, [])
        #print (uid)

        return result.pop(0) if result else {}

    def all(self, uid):
        result = self.results.pop(uid, {})
        #print (uid)

        return result if result else []

    def one_orig(self):
        if self.status == 'success':
            return self.fetchone()   #fetchone pops first record
        return {}

    def all_orig(self):
        if self.status == 'success':
            return self.fetchall()
        return []

    def fetchone(self):
        result = self.cursor.fetchone()
        return result if result else {}

    def fetchall(self):
        result = self.cursor.fetchall()
        return result if result else {}

    def row_count(self):
        #if self.status == 'error':
        #    return 0
        if self.cursor:
            return self.cursor.rowcount
        else:
            return 0



    def parse_select(self, **kwargs):

        sql = ''
        table = kwargs.get('select', '')
        select = kwargs.get('columns', '')
        where = kwargs.get('where', '')
        join = kwargs.get('join', '')
        group_by = kwargs.get('group by', kwargs.get('group_by', ''))
        order_by = kwargs.get('order by', kwargs.get('order_by', ''))
        limit = kwargs.get('limit', '')

        if not select and type(select) not in (type(' '), type([])):
            return {'error': 'No select value or incorrect data type: {}'.format(type(select)),
                    'status': 'error'
                    }
        else:
            sql += 'select {} '.format(select if type(select) == type(' ') else ', '.join(select))

        if not table:
            return {'error': 'No table to select from',
                    'status': 'error'
                    }
        else:
            sql += 'from {}'.format(table)

        if join:
            if type(join) not in (type(' '), type([]), type({})):
                return {'error': 'inner join incorrect data type: {}'.format(type(join)),
                        'status': 'error'
                        }
            else:
                if type(join) == type(' ') or type(join) == type({}):
                    join = [join]
                for j in join:
                    join_type = j.get('type', '')
                    tbl_name = j.get('tbl_name', '')
                    tbl_alias = j.get('tbl_alias', '')
                    if not tbl_alias:
                        tbl_alias = tbl_name
                    tbl_column = j.get('tbl_column', '')
                    condition = j.get('condition', '')
                    cond_tbl_name = j.get('cond_tbl_name', '')
                    cond_tbl_column = j.get('cond_tbl_column', '')

                    join_str = ''
                    if tbl_name:
                        join_str += ' {join} join {tbl_name} as {tbl_alias} '.format(join=join_type,
                                                                                     tbl_name=tbl_name,
                                                                                     tbl_alias=tbl_alias)
                        if tbl_column:
                            join_str += ' {condition} {tbl_alias}.{tbl_column} '.format(condition='on' if condition else '',
                                                                                        tbl_alias=tbl_alias,
                                                                                        tbl_column=tbl_column)
                            if condition:
                                join_str += ' {condition} {cond_tbl_name}.{cond_tbl_column}'.format(condition=condition,
                                                                                        cond_tbl_name=cond_tbl_name,
                                                                                        cond_tbl_column=cond_tbl_column)

                    sql += ' {} '.format(join_str)

        if where:
            sql += ' where {} '.format(where)
        if group_by:
            sql += ' group by {} '.format(group_by)
            if not order_by:
                """
                From the MySql Select docs:
                If you use GROUP BY, output rows are sorted according to the GROUP BY
                columns as if you had an ORDER BY for the same columns. To avoid
                the overhead of sorting that GROUP BY produces, add ORDER BY NULL:
                """
                sql += 'order by NULL '
        if order_by:
            sql += ' order by {} '.format(order_by)
        if limit:
            sql += ' limit {} '.format(limit)

        return {'sql': sql,
                'status': 'success'
                }

    def parse_insert(self, **kwargs):

        sql = ''
        table = kwargs.get('insert', '')
        ignore = kwargs.get('ignore', False)
        data = kwargs.get('data', {})

        if table and data:
            columns = []
            values = []
            for d in data:
                columns.append(d)
                values.append(data[d])
            sql += 'insert {ignore} into {table} ({columns}) values ("{values}")'.format(
                                                                                        ignore='ignore' if ignore else '',
                                                                                        table=table,
                                                                                        columns=','.join(columns),
                                                                                        values='","'.join(values)
                                                                                        )

        else:
            return {'error': 'Minumum parameters for insert not supplied: insert: {}, '
                             'data keys: {}'.format(table, data.keys()),
                    'status': 'error'
                    }

        return {'sql': sql,
                'status': 'success'
                }

    def parse_delete(self, **kwargs):

        sql = ''
        table = kwargs.get('delete', '')
        where = kwargs.get('where', {})
        order_by = kwargs.get('order_by', '')
        limit = kwargs.get('limit', '')

        if table:
            sql += 'delete from {table}'.format(table=table)
            if where:
                sql += ' where {} '.format(where)
            if order_by:
                sql += ' order by {} '.format(order_by)
            if limit:
                sql += ' limit {} '.format(limit)

        else:
            return {'error': 'Minumum parameters for delete not supplied: delete table: {}, '
                             ''.format(table),
                    'status': 'error'
                    }

        return {'sql': sql,
                'status': 'success'
                }

    def parse_update(self, **kwargs):

        sql = ''
        table = kwargs.get('update', '')
        ignore = kwargs.get('ignore', False)
        data = kwargs.get('data', {})
        where = kwargs.get('where', {})
        order_by = kwargs.get('order_by', '')
        limit = kwargs.get('limit', '')

        if table and data:
            assignment = []
            for d in data:
                assignment.append('{}="{}"'.format(d, data[d]))
            sql += 'update {ignore} {table} set {assignment}'.format(
                                                                                        ignore='ignore' if ignore else '',
                                                                                        table=table,
                                                                                        assignment=','.join(assignment),
                                                                                        )
            if where:
                sql += ' where {} '.format(where)
            if order_by:
                sql += ' order by {} '.format(order_by)
            if limit:
                sql += ' limit {} '.format(limit)

        else:
            return {'error': 'Minumum parameters for update not supplied: update table: {}, '
                             'data keys: {}'.format(table, data.keys()),
                    'status': 'error'
                    }

        return {'sql': sql,
                'status': 'success'
                }

    def db_command(self, *args, **kwargs):
        #logger.debug('sql_get() - args: {}'.format(args))
        #logger.debug('sql_get() - kwargs: {}'.format(kwargs))
        data = {}
        errors = []
        self.error = ''
        self.status = ''
        self.sql = ''
        self.validated = False
        sql = kwargs.get('sql', '')
        uid = kwargs.get('uid', '')

        #print (uid)
        if sql and type(sql) == type(' '):
            self.sql_query(sql, uid=uid)
            self.sql = sql
        else:
            if 'select' in kwargs:
                command = 'select'
            elif 'insert' in kwargs:
                command = 'insert'
            elif 'delete' in kwargs:
                command = 'delete'
            elif 'update' in kwargs:
                command = 'update'
            else:
                command = 'unknown'
            self.validate_query(*args, **kwargs)
            #logger.debug ('{}, {}'.format(self.validated, command))
            if self.validated and command != 'unknown':
                result = {'status': 'error'}
                if command == 'select':
                    result = self.parse_select(**kwargs)
                elif command == 'insert':
                    result = self.parse_insert(**kwargs)
                elif command == 'delete':
                    result = self.parse_delete(**kwargs)
                elif command == 'update':
                    result = self.parse_update(**kwargs)
                if result['status'] == 'success':
                    self.sql_query(result['sql'], uid=uid)
                    self.sql = result['sql']
                else:
                    self.set_status(status=result['status'], error=result['error'])
            else:
                self.set_status(status='error', error='{} query not validated with error(s): {}'.format(command.title(), self.error))

        return self


    def validate_query(self, *args, **kwargs):
        """
        Method to be sub classed
        :param args:
        :param kwargs:
        :return:
        """
        self.error = ''
        self.validated = True

    def get_list(self, uid, field):

        result = self.all(uid)

        field_list = []

        for r in result:
            if field in r:
                field_list.append(r[field])
            else:
                break

        return field_list

"""
mysql DB test functions
"""
def get_all():
    fn = sys._getframe().f_code.co_name
    logger.info('{}Test case: {} start'.format(TEST_CASE, fn))
    sql = 'select * from test_table'
    uid = gen_uid()
    result = db.db_command(sql=sql, uid=uid).all(uid)
    logger.info('select result: {}'.format(result))
    logger.info('{}Test case: {} end\n'.format(TEST_CASE, fn))

def get_one():
    fn = sys._getframe().f_code.co_name
    logger.info('{}Test case: {} start'.format(TEST_CASE, fn))
    sql = 'select * from test_table where name = "name1"'
    uid = gen_uid()
    result = db.db_command(sql=sql, uid=uid).one(uid)
    logger.info('select result: {}'.format(result))
    logger.info('{}Test case: {} end\n'.format(TEST_CASE, fn))

def sql_error():
    fn = sys._getframe().f_code.co_name
    logger.info('{}Test case: {} start'.format(TEST_CASE, fn))
    sql = 'select * error from test_table where name = "name1"'
    uid = gen_uid()
    result = db.db_command(sql=sql, uid=uid).one(uid)
    logger.info('select result: {}'.format(result))
    logger.info('{}Test case: {} end\n'.format(TEST_CASE, fn))

def reconnect():
    fn = sys._getframe().f_code.co_name
    logger.info('{}Test case: {} start'.format(TEST_CASE, fn))
    db.disconnect()
    db.connect()
    logger.info('{}Test case: {} end\n'.format(TEST_CASE, fn))

def connect(reconnect=False):
    fn = sys._getframe().f_code.co_name
    logger.info('{}Test case: {} start'.format(TEST_CASE, fn))
    db.connect(reconnect=reconnect)
    logger.info('{}Test case: {} end\n'.format(TEST_CASE, fn))

def disconnect():
    fn = sys._getframe().f_code.co_name
    logger.info('{}Test case: {} start'.format(TEST_CASE, fn))
    db.disconnect()
    logger.info('{}Test case: {} end\n'.format(TEST_CASE, fn))


if __name__ == '__main__':
    LEVEL = logging.DEBUG
    logger.setLevel(LEVEL)
    ch.setLevel(LEVEL)
    #db = Database('1.1.1.1', local_host['user'], local_host['password'], 'db_test')
    db = Database(local_host['host'], local_host['user'], local_host['password'], 'db_test')

    #get_all()

    #get_one()

    sql_error()

    #reconnect()
    get_one()

    #connect()
    #connect(reconnect=True)
    #get_one()

    #disconnect()
    #get_one()




