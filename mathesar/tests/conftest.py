"""
This inherits the fixtures in the root conftest.py
"""
import pytest
import logging
from copy import deepcopy

from django.core.files import File
from django.core.cache import cache
from django.conf import settings
from django.test.utils import setup_databases, teardown_databases

from sqlalchemy import Column, MetaData, Integer
from sqlalchemy import Table as SATable

from db.tables.operations.select import get_oid_from_table
from db.tables.operations.create import create_mathesar_table as actual_create_mathesar_table
from db.columns.operations.select import get_column_attnum_from_name
from db.schemas.utils import get_schema_oid_from_name

from mathesar.models import Schema, Table, Database, DataFile
from mathesar.imports.csv import create_table_from_csv
from mathesar.models import Column as mathesar_model_column


@pytest.fixture(autouse=True)
def automatically_clear_cache():
    """
    Makes sure Django cache is cleared before every test.
    """
    logger = logging.getLogger("django cache clearing fixture")
    logger.debug("clearing cache")
    cache.clear()
    yield


#   @pytest.fixture(autouse=True)
#   def delete_all_models(django_db_blocker):
#       yield
#       logger = logging.getLogger('django model clearing fixture')
#       with django_db_blocker.unblock():
#           all_models = {Table, Schema, Database}
#           for model in all_models:
#               count = model.current_objects.count()
#               logger.debug(f'deleting {count} instances of {model}')
#               model.current_objects.all().delete()


# TODO autouse redundant?
@pytest.fixture(scope="function", autouse=True)
def django_db_setup(request, django_db_blocker):
    """
    A stripped down version of pytest-django's original django_db_setup fixture
    See: https://github.com/pytest-dev/pytest-django/blob/master/pytest_django/fixtures.py#L96
    Also see: https://pytest-django.readthedocs.io/en/latest/database.html#using-a-template-database-for-tests

    Removes most additional options (use migrations, keep / create db, etc.)
    Adds 'aliases' to the call to setup_databases() which restrict Django to only
    building and destroying the default Django db, and not our tables dbs.
    """
    verbosity = request.config.option.verbose
    with django_db_blocker.unblock():
        db_cfg = setup_databases(
            verbosity=verbosity,
            interactive=False,
            aliases=["default"],
        )
    yield
    with django_db_blocker.unblock():
        try:
            teardown_databases(db_cfg, verbosity=verbosity)
        except Exception as exc:
            request.node.warn(
                pytest.PytestWarning(
                    "Error when trying to teardown test databases: %r" % exc
                )
            )


@pytest.fixture(scope="function", autouse=True)
def test_db_model(test_db_name, django_db_blocker):
    with django_db_blocker.unblock():
        database_model = Database.current_objects.create(name=test_db_name)
    return database_model


@pytest.fixture
def add_db_to_dj_settings():
    """
    If the Django layer should be aware of a db, it should be added to settings.DATABASES dict.
    """
    logger = logging.getLogger("add_db_to_dj_settings")
    logger.debug("init")
    logger.debug(f"settings.DATABASES initially {list(settings.DATABASES.keys())}")
    added_dbs = set()
    def _add(db_name):
        logger.debug(f"adding {db_name}")
        reference_entry = settings.DATABASES["default"]
        new_entry = dict(
            USER=reference_entry['USER'],
            PASSWORD=reference_entry['PASSWORD'],
            HOST=reference_entry['HOST'],
            PORT=reference_entry['PORT'],
            NAME=db_name,
        )
        settings.DATABASES[db_name] = new_entry
        cache.clear()
        added_dbs.add(db_name)
        return db_name
    yield _add
    logger.debug(f"about to clean up {added_dbs}")
    for db_name in added_dbs:
        settings.DATABASES.pop(db_name, None)
        logger.debug(f"cleaned up {db_name}")
    logger.debug("exit")


@pytest.fixture
def create_temp_dj_db(add_db_to_dj_settings, create_temp_db):
    """
    Like create_temp_db, but adds the new db to Django's settings.DATABASES dict.
    """
    def _create_and_add(db_name):
        create_temp_db(db_name)
        add_db_to_dj_settings(db_name)
        return db_name
    yield _create_and_add


@pytest.fixture(autouse=True)
def enable_db_access_for_all_tests(transactional_db):
    pass


@pytest.fixture(scope='session')
def patents_csv_filepath():
    return 'mathesar/tests/data/patents.csv'


@pytest.fixture(scope='session')
def paste_filename():
    return 'mathesar/tests/data/patents.txt'


@pytest.fixture(scope='session')
def headerless_patents_csv_filepath():
    return 'mathesar/tests/data/headerless_patents.csv'


@pytest.fixture(scope='session')
def patents_url():
    return 'https://thisisafakeurl.com'


@pytest.fixture(scope='session')
def patents_url_filename():
    return 'mathesar/tests/data/api_patents.csv'


@pytest.fixture(scope='session')
def data_types_csv_filepath():
    return 'mathesar/tests/data/data_types.csv'


@pytest.fixture(scope='session')
def col_names_with_spaces_csv_filepath():
    return 'mathesar/tests/data/col_names_with_spaces.csv'


@pytest.fixture(scope='session')
def col_headers_empty_csv_filepath():
    return 'mathesar/tests/data/col_headers_empty.csv'


@pytest.fixture(scope='session')
def non_unicode_csv_filepath():
    return 'mathesar/tests/data/non_unicode_files/utf_16_le.csv'


@pytest.fixture
def empty_nasa_table(patent_schema, engine_with_schema):
    engine, _ = engine_with_schema
    NASA_TABLE = 'NASA Schema List'
    db_table = SATable(
        NASA_TABLE, MetaData(bind=engine),
        Column('id', Integer, primary_key=True),
        schema=patent_schema.name,
    )
    db_table.create()
    db_table_oid = get_oid_from_table(db_table.name, db_table.schema, engine)
    table = Table.current_objects.create(oid=db_table_oid, schema=patent_schema)

    yield table

    table.delete_sa_table()
    table.delete()


@pytest.fixture
def patent_schema(create_schema):
    PATENT_SCHEMA = 'Patents'
    yield create_schema(PATENT_SCHEMA)


@pytest.fixture
def create_schema(test_db_model, create_db_schema):
    """
    Creates a DJ Schema model factory, making sure to track and clean up new instances
    """
    engine = test_db_model._sa_engine
    def _create_schema(schema_name):
        create_db_schema(schema_name, engine)
        schema_oid = get_schema_oid_from_name(schema_name, engine)
        schema_model, _ = Schema.current_objects.get_or_create(oid=schema_oid, database=test_db_model)
        return schema_model
    yield _create_schema
    # NOTE: Schema model is not cleaned up. Maybe invalidate cache?


@pytest.fixture
def create_mathesar_table(create_db_schema):
    def _create_mathesar_table(
        table_name, schema_name, columns, engine, metadata=None,
    ):
        # We use a fixture for schema creation, so that it gets cleaned up.
        create_db_schema(schema_name, engine, schema_mustnt_exist=False)
        return actual_create_mathesar_table(
            name=table_name, schema=schema_name, columns=columns,
            engine=engine, metadata=metadata
        )
    yield _create_mathesar_table


@pytest.fixture
def create_patents_table(patents_csv_filepath, patent_schema, create_table):
    schema_name = patent_schema.name
    csv_filepath = patents_csv_filepath

    def _create_table(table_name, schema_name=schema_name):
        return create_table(
            table_name=table_name,
            schema_name=schema_name,
            csv_filepath=csv_filepath,
        )

    return _create_table


@pytest.fixture
def create_table(create_schema):
    def _create_table(table_name, schema_name, csv_filepath):
        data_file = _get_datafile_for_path(csv_filepath)
        schema_model = create_schema(schema_name)
        return create_table_from_csv(data_file, table_name, schema_model)
    return _create_table


def _get_datafile_for_path(path):
    with open(path, 'rb') as file:
        datafile = DataFile.objects.create(file=File(file))
        return datafile


@pytest.fixture
def create_column():
    def _create_column(table, column_data):
        column = table.add_column(column_data)
        attnum = get_column_attnum_from_name(table.oid, [column.name], table.schema._sa_engine)
        column = mathesar_model_column.current_objects.get_or_create(attnum=attnum, table=table)
        return column[0]
    return _create_column


@pytest.fixture
def custom_types_schema_url(schema, live_server):
    return f"{live_server}/{schema.database.name}/{schema.id}"


@pytest.fixture
def create_column_with_display_options():
    def _create_column(table, column_data):
        column = table.add_column(column_data)
        attnum = get_column_attnum_from_name(table.oid, [column.name], table.schema._sa_engine)
        column = mathesar_model_column.current_objects.get_or_create(
            attnum=attnum,
            table=table,
            display_options=column_data.get('display_options', None)
        )
        return column[0]
    return _create_column
