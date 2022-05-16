import pytest
import logging
from django.conf import settings
from django.core.cache import cache

from mathesar.reflection import reflect_db_objects
from mathesar.models import Table, Schema, Database


@pytest.fixture(autouse=True)
def delete_all_models():
    yield
    logger = logging.getLogger('delete_all_models')
    models = {Table, Schema, Database}
    for model in models:
        count = model.current_objects.count()
        logger.debug(f'deleting {count} instances of {model}')
        model.current_objects.all().delete()


@pytest.fixture
def database_api_db(create_temp_dj_db, uid):
    db_name = "test_database_api_db" + uid
    create_temp_dj_db(db_name)
    return db_name


def test_database_reflection_new(database_api_db):
    reflect_db_objects()
    assert Database.objects.filter(name=database_api_db).exists()


def test_database_reflection_delete(database_api_db):
    reflect_db_objects()
    db = Database.objects.get(name=database_api_db)
    assert db.deleted is False

    del settings.DATABASES[database_api_db]
    cache.clear()
    reflect_db_objects()
    db.refresh_from_db()
    assert db.deleted is True


def test_database_reflection_delete_schema(database_api_db):
    reflect_db_objects()
    db = Database.objects.get(name=database_api_db)

    Schema.objects.create(oid=1, database=db)
    # We expect the test schema + 'public'
    assert Schema.objects.filter(database=db).count() == 2

    del settings.DATABASES[database_api_db]
    cache.clear()
    reflect_db_objects()
    assert Schema.objects.filter(database=db).count() == 0


def test_database_reflection_delete_table(database_api_db):
    reflect_db_objects()
    db = Database.objects.get(name=database_api_db)

    schema = Schema.objects.create(oid=1, database=db)
    Table.objects.create(oid=2, schema=schema)
    assert Table.objects.filter(schema__database=db).count() == 1

    del settings.DATABASES[database_api_db]
    cache.clear()
    reflect_db_objects()
    assert Table.objects.filter(schema__database=db).count() == 0


def check_database(database, response_database):
    assert database.id == response_database['id']
    assert database.name == response_database['name']
    assert database.deleted == response_database['deleted']
    assert 'supported_types_url' in response_database
    assert '/api/ui/v0/databases/' in response_database['supported_types_url']
    assert response_database['supported_types_url'].endswith('/types/')


def test_database_list(client, test_db_name, database_api_db):
    response = client.get('/api/db/v0/databases/')
    response_data = response.json()

    expected_databases = {
        test_db_name: Database.objects.get(name=test_db_name),
        database_api_db: Database.objects.get(name=database_api_db),
    }

    assert response.status_code == 200
    assert response_data['count'] == 2
    assert len(response_data['results']) == 2
    for response_database in response_data['results']:
        expected_database = expected_databases[response_database['name']]
        check_database(expected_database, response_database)


def test_database_list_deleted(client, test_db_name, database_api_db):
    reflect_db_objects()
    del settings.DATABASES[database_api_db]

    cache.clear()
    response = client.get('/api/db/v0/databases/')
    response_data = response.json()

    expected_databases = {
        test_db_name: Database.objects.get(name=test_db_name),
        database_api_db: Database.objects.get(name=database_api_db),
    }

    assert response.status_code == 200
    assert response_data['count'] == 2
    assert len(response_data['results']) == 2
    for response_database in response_data['results']:
        expected_database = expected_databases[response_database['name']]
        check_database(expected_database, response_database)


@pytest.mark.parametrize('deleted', [True, False])
def test_database_list_filter_deleted(client, deleted, test_db_name, database_api_db):
    reflect_db_objects()
    del settings.DATABASES[database_api_db]

    cache.clear()
    response = client.get(f'/api/db/v0/databases/?deleted={deleted}')
    response_data = response.json()

    expected_databases = {
        False: Database.current_objects.get(name=test_db_name),
        True: Database.current_objects.get(name=database_api_db),
    }

    assert response.status_code == 200
    assert response_data['count'] == 1
    assert len(response_data['results']) == 1

    expected_database = expected_databases[deleted]
    response_database = response_data['results'][0]
    check_database(expected_database, response_database)


def test_database_list_ordered_by_id(client, test_db_name, database_api_db, create_temp_dj_db):
    reflect_db_objects()
    test_db_name_1 = "mathesar_db_test_1"
    create_temp_dj_db(test_db_name_1)
    cache.clear()
    expected_databases = [
        Database.objects.get(name=test_db_name),
        Database.objects.get(name=database_api_db),
        Database.objects.get(name=test_db_name_1),
    ]
    expected_databases = sorted(expected_databases, key=lambda db: db.id)
    sort_field = "id"
    response = client.get(f'/api/db/v0/databases/?sort_by={sort_field}')
    response_data = response.json()
    response_databases = response_data['results']
    response_databases = sorted(response_databases, key=lambda db: db['id'])
    comparison_tuples = zip(expected_databases, response_databases)
    for comparison_tuple in comparison_tuples:
        check_database(comparison_tuple[0], comparison_tuple[1])


def test_database_list_ordered_by_name(client, test_db_name, database_api_db, create_temp_dj_db):
    reflect_db_objects()
    test_db_name_1 = "mathesar_db_test_1"
    test_db_name_2 = "mathesar_db_test_2"
    create_temp_dj_db(test_db_name_1)
    create_temp_dj_db(test_db_name_2)

    cache.clear()
    expected_databases = [
        Database.objects.get(name=test_db_name),
        Database.objects.get(name=test_db_name_1),
        Database.objects.get(name=test_db_name_2),
        Database.objects.get(name=database_api_db),
    ]
    sort_field = "name"
    response = client.get(f'/api/db/v0/databases/?sort_by={sort_field}')
    response_data = response.json()
    response_databases = response_data['results']
    comparison_tuples = zip(expected_databases, response_databases)
    for comparison_tuple in comparison_tuples:
        check_database(comparison_tuple[0], comparison_tuple[1])


def test_database_detail(client):
    expected_database = Database.objects.get()

    response = client.get(f'/api/db/v0/databases/{expected_database.id}/')
    response_database = response.json()

    assert response.status_code == 200
    check_database(expected_database, response_database)
