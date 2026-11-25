"""Deployment checks using temporary SQLite, without calling external services."""
import unittest
from datetime import datetime
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch, AsyncMock

try:
    from uvloop import run as run_async
except ImportError:
    from asyncio import run as run_async
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import make_url
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from app.config import Settings, get_settings
from app.database import get_session
from app.main import app
from app.middleware import COOKIE_NAME, create_token
from app.models.user import User
from app.models.dokumen import DokumenPerencanaan
from app.models.kejadian import Kejadian
from app.routers import auth


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool,
                                    connect_args={'check_same_thread': False})
        SQLModel.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.user = User(email='admin@example.test', role='admin', name='Admin')
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)
        doc = DokumenPerencanaan(nama='RKPD Test', jenis='RKPD', tahun_awal=2026, tahun_akhir=2026)
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)
        event = Kejadian(dokumen_id=doc.id, jenis_kejadian='Rapat', judul_kejadian='Rapat Test', tanggal_kejadian=datetime(2026, 11, 15))
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        self.event_id = event.id
        async def session_override():
            yield self.db
        app.dependency_overrides[get_session] = session_override
        self.patches = [patch('app.middleware.engine', self.engine),
                        patch('app.routers.chatbot.engine', self.engine),
                        patch.object(app, 'root_path', '/simetri'),
                        patch.object(get_settings(), 'ROOT_PATH', '/simetri'),
                        patch.object(get_settings(), 'COOKIE_SECURE', True)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        app.dependency_overrides.clear()
        for p in reversed(self.patches):
            p.stop()
        self.db.close()
        self.engine.dispose()

    def run_async(self, fn):
        # uvloop avoids the restricted environment's socketpair wakeup limitation.
        run_async(fn())

    def client(self):
        return AsyncClient(transport=ASGITransport(app=app), base_url='https://example.test')

    def test_prefix_redirects_and_static(self):
        async def check():
            async with self.client() as c:
                for path in ('/', '/simetri/'):
                    r = await c.get(path)
                    self.assertEqual(r.headers['location'], '/simetri/kronologi')
                for path in ('/login', '/simetri/login'):
                    r = await c.get(path, headers={'x-forwarded-prefix': '/evil', 'referer': 'https://evil.test'})
                    self.assertEqual(r.status_code, 200)
                    self.assertIn('href="/simetri/auth/google"', r.text)
                    self.assertNotIn('/evil/', r.text)
                for path in ('/static/css/app.css', '/simetri/static/css/app.css', '/simetri/static/js/app.js'):
                    self.assertEqual((await c.get(path)).status_code, 200)
                r = await c.get('/simetri/kronologi')
                self.assertEqual(r.headers['location'], '/simetri/login')
                r = await c.get('/simetri/dokumen')
                self.assertEqual(r.headers['location'], '/simetri/login')
        self.run_async(check)

    def test_authenticated_pages_and_fragments(self):
        async def check():
            async with self.client() as c:
                c.cookies.set(COOKIE_NAME, create_token(self.user.id, self.user.email))
                for path in ('/kronologi', '/arsip', '/agenda', '/agenda?bulan=2026-99',
                             '/dokumen', '/chatbot', '/admin/users', '/admin/audit',
                             '/kronologi/form', f'/kronologi/detail/{self.event_id}',
                             '/arsip/form', '/agenda/form'):
                    r = await c.get('/simetri' + path)
                    self.assertEqual(r.status_code, 200, path + ': ' + r.text[:300])
                    self.assertNotIn('action="/lampiran/', r.text)
                    self.assertNotIn('hx-get="/kronologi', r.text)
                r = await c.get('/simetri/kronologi', headers={'HX-Request': 'true'})
                self.assertIn('hx-get="/simetri/', r.text)
                r = await c.get('/simetri/logout')
                self.assertEqual(r.headers['location'], '/simetri/login')
                self.assertIn('Path=/simetri', r.headers['set-cookie'])
        self.run_async(check)

    def test_oauth_state_and_disabled_dev_login(self):
        async def check():
            async with self.client() as c:
                self.assertEqual((await c.get('/simetri/auth/dev-login')).status_code, 404)
                with patch.object(auth, '_handle_oauth_code', new_callable=AsyncMock) as exchange:
                    r = await c.get('/simetri/oauthcallback?code=fake&state=bad')
                    self.assertIn('invalid_state', r.headers['location'])
                    exchange.assert_not_called()
                    r = await c.get('/simetri/auth/google')
                    query = parse_qs(urlsplit(r.headers['location']).query)
                    self.assertEqual(query['redirect_uri'], [get_settings().GOOGLE_REDIRECT_URI])
                    self.assertEqual(query['scope'], ['openid email profile'])
                    self.assertIn('Secure', r.headers['set-cookie'])
                    from fastapi.responses import RedirectResponse
                    exchange.return_value = RedirectResponse('/simetri/kronologi')
                    r = await c.get('/simetri/oauthcallback', params={'code': 'fake', 'state': query['state'][0]})
                    exchange.assert_awaited_once()
                    self.assertIn('Max-Age=0', r.headers['set-cookie'])
        self.run_async(check)

    def test_attachments_require_login(self):
        async def check():
            async with self.client() as c:
                r = await c.post(f'/simetri/lampiran/kejadian/{self.event_id}/upload',
                                 data={'tipe': 'link_eksternal', 'external_url': 'https://example.test/doc'})
                self.assertEqual(r.status_code, 302)
                self.assertEqual(r.headers['location'], '/simetri/login')
        self.run_async(check)

    def test_kronologi_document_scope(self):
        user = User(email='opd@example.test', role='user_opd', name='OPD', opd_id=None)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        event = self.db.get(Kejadian, self.event_id)
        doc_id = event.dokumen_id
        async def check():
            async with self.client() as c:
                c.cookies.set(COOKIE_NAME, create_token(user.id, user.email))
                # Empty access scope must never fall back to all records.
                for query in ('', f'?dokumen_id={doc_id}'):
                    r = await c.get('/simetri/kronologi' + query)
                    self.assertEqual(r.status_code, 200)
                    self.assertNotIn('Rapat Test', r.text)
                for action in ('detail', 'form'):
                    r = await c.get(f'/simetri/kronologi/{action}/{self.event_id}')
                    self.assertEqual(r.status_code, 403)
                r = await c.delete(f'/simetri/kronologi/delete/{self.event_id}')
                self.assertEqual(r.status_code, 403)
                r = await c.post('/simetri/kronologi/save', data={'dokumen_id': doc_id})
                self.assertEqual(r.status_code, 403)
                r = await c.post(f'/simetri/lampiran/kejadian/{self.event_id}/upload',
                                 data={'tipe': 'link_eksternal', 'external_url': 'https://example.test/doc'})
                self.assertEqual(r.status_code, 403)
        self.run_async(check)

    def test_pagu_page_requires_login_and_renders(self):
        async def check():
            async with self.client() as c:
                # Tanpa login -> redirect ke login
                r = await c.get('/simetri/pagu')
                self.assertEqual(r.status_code, 302)
                self.assertIn('/login', r.headers['location'])

                # Dengan login -> 200 OK dan render halaman pagu
                c.cookies.set(COOKIE_NAME, create_token(self.user.id, self.user.email))
                r = await c.get('/simetri/pagu')
                self.assertEqual(r.status_code, 200)
                self.assertIn('Penyusunan Pagu', r.text)
        self.run_async(check)

    def test_pagu_matrix_and_crud(self):
        from app.models.pagu import KategoriBelanja, RincianAnggaran
        from app.models.user import TaOpd

        opd = TaOpd(id_sub_pd=101, id_pd=101, kode="1.01.01", nama_pd="Dinas Pendidikan Test", is_pd=1, aktif=1)
        self.db.add(opd)
        kat = KategoriBelanja(id=201, nomor=1, jenis="BELANJA PEGAWAI", kategori="GAJI PNS TEST")
        self.db.add(kat)
        self.db.commit()

        async def check():
            async with self.client() as c:
                c.cookies.set(COOKIE_NAME, create_token(self.user.id, self.user.email))

                # 1. Matriks view menampilkan OPD dan kolom Kategori
                r = await c.get('/simetri/pagu')
                self.assertEqual(r.status_code, 200)
                self.assertIn('Dinas Pendidikan Test', r.text)
                self.assertIn('GAJI PNS TEST', r.text)

                # 2. Form modal tambah
                r = await c.get('/simetri/pagu/form?id_pd=101&id_kategori=201')
                self.assertEqual(r.status_code, 200)
                self.assertIn('Tambah Rincian Anggaran', r.text)

                # 3. Create rincian anggaran
                r = await c.post('/simetri/pagu/save', data={
                    'id_pd': 101,
                    'id_kategori': 201,
                    'uraian': 'Gaji Guru Test',
                    'uraian_belanja': 'Belanja Gaji Pokok',
                    'anggaran': '150000000',
                    'tags': '#TestTag'
                })
                self.assertIn(r.status_code, (200, 303))

                # Ambil record dari db
                rincian = self.db.exec(select(RincianAnggaran).where(RincianAnggaran.uraian == 'Gaji Guru Test')).first()
                self.assertIsNotNone(rincian)
                self.assertEqual(int(rincian.anggaran), 150000000)

                # 4. Form modal edit (combobox id_pd tidak ditampilkan, otomatis terpilih via hidden input)
                r = await c.get(f'/simetri/pagu/form/{rincian.id}')
                self.assertEqual(r.status_code, 200)
                self.assertIn('Edit Rincian Anggaran', r.text)
                self.assertIn('Gaji Guru Test', r.text)
                self.assertNotIn('<select name="id_pd"', r.text)
                self.assertIn('type="hidden" name="id_pd"', r.text)

                # 5. Update rincian anggaran
                r = await c.post('/simetri/pagu/save', data={
                    'id': rincian.id,
                    'id_pd': 101,
                    'id_kategori': 201,
                    'uraian': 'Gaji Guru Diperbarui',
                    'uraian_belanja': 'Belanja Gaji Pokok Update',
                    'anggaran': '200000000',
                    'tags': '#TestTag #Updated'
                })
                self.assertIn(r.status_code, (200, 303))

                self.db.refresh(rincian)
                self.assertEqual(rincian.uraian, 'Gaji Guru Diperbarui')
                self.assertEqual(int(rincian.anggaran), 200000000)

                # 6. Halaman rincian belanja OPD
                r = await c.get('/simetri/pagu/opd/101')
                self.assertEqual(r.status_code, 200)
                self.assertIn('Dinas Pendidikan Test', r.text)
                self.assertIn('Gaji Guru Diperbarui', r.text)

                # 7. Delete rincian anggaran
                r = await c.delete(f'/simetri/pagu/delete/{rincian.id}')
                self.assertIn(r.status_code, (200, 303))

                deleted = self.db.get(RincianAnggaran, rincian.id)
                self.assertIsNone(deleted)

        self.run_async(check)


class ConfigurationTests(unittest.TestCase):
    def test_public_url_and_database_encoding(self):
        s = Settings(_env_file=None, SERVER_URL='https://example.test/simetri/',
                     ROOT_PATH='/simetri/', SECRET_KEY='x' * 48, COOKIE_SECURE=True,
                     GOOGLE_REDIRECT_URI='', DB_PASSWORD='p@ss:/?#')
        self.assertEqual(s.GOOGLE_REDIRECT_URI, 'https://example.test/simetri/oauthcallback')
        self.assertEqual(s.url_path('/simetri/agenda'), '/simetri/agenda')
        self.assertEqual(make_url(s.database_url).password, 'p@ss:/?#')
        self.assertEqual(make_url(s.database_url).query['sslmode'], s.DB_SSLMODE)

    def test_reject_invalid_production_configuration(self):
        for values in ({'SECRET_KEY': 'short'}, {'COOKIE_SECURE': False},
                       {'GOOGLE_REDIRECT_URI': 'http://localhost:8000/auth/google'}):
            kwargs = dict(SERVER_URL='https://example.test/simetri', ROOT_PATH='/simetri',
                          SECRET_KEY='x' * 48, COOKIE_SECURE=True, GOOGLE_REDIRECT_URI='')
            kwargs.update(values)
            with self.assertRaises(ValueError):
                Settings(_env_file=None, **kwargs)
