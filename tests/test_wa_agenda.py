import asyncio
import json
import unittest
from datetime import date, datetime
from unittest.mock import patch, AsyncMock

from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool

from app.models.user import User
from app.models.agenda import Agenda
from app.services.wa_archive_service import get_user_by_whatsapp_phone
from app.services.wa_agenda_service import (
    is_agenda_request,
    parse_agenda_date,
    handle_whatsapp_agenda,
)
from app.routers import whatsapp


class WhatsAppAgendaTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            'sqlite://',
            poolclass=StaticPool,
            connect_args={'check_same_thread': False},
        )
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

        # 1. Registered active user
        self.user = User(
            email='perencana@bappeda.test',
            name='Herry Prihanto',
            no_hp='081234567890',
            role='admin',
            is_active=True,
        )
        self.session.add(self.user)

        # 2. Inactive user
        self.inactive_user = User(
            email='inactive@bappeda.test',
            name='Inactive User',
            no_hp='089999999999',
            role='perencana',
            is_active=False,
        )
        self.session.add(self.inactive_user)

        # 3. Seed agenda items on 2026-10-29
        self.target_date = date(2026, 10, 29)
        self.session.add(
            Agenda(
                id=1,
                judul='Rapat Koordinasi Teknis RKPD 2027',
                kategori='Rapat',
                tanggal=self.target_date,
                jam_mulai='09:00',
                jam_selesai='11:30',
                tempat='Ruang Rapat Bappeda Lt. 2',
                bidang='Perekonomian',
                keterangan='<p>Pembahasan awal indikator makro pembangunan.</p>',
            )
        )
        self.session.add(
            Agenda(
                id=2,
                judul='Musrenbang Kecamatan Tegal Barat',
                kategori='Undangan',
                tanggal=self.target_date,
                jam_mulai='13:00',
                jam_selesai='',
                tempat='Pendopo Kecamatan Tegal Barat',
                bidang='PPEPD',
                keterangan='Penetapan usulan prioritas.',
            )
        )
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_is_agenda_request(self):
        self.assertTrue(is_agenda_request('simetri-agenda hari ini'))
        self.assertTrue(is_agenda_request('SIMETRI-AGENDA tanggal 2026-10-29'))
        self.assertTrue(is_agenda_request('simetri-agenda tanggal 29-10-2026'))
        self.assertTrue(is_agenda_request('!simetri-agenda'))
        self.assertTrue(is_agenda_request('/simetri-agenda'))
        self.assertTrue(is_agenda_request('simetri-agenda'))

        self.assertFalse(is_agenda_request('simetri-cari agenda'))
        self.assertFalse(is_agenda_request('simetri agenda rapat'))
        self.assertFalse(is_agenda_request('halo simetri'))

    def test_parse_agenda_date(self):
        ref_now = datetime(2026, 10, 28, 8, 0, 0)
        # Hari ini
        self.assertEqual(parse_agenda_date('simetri-agenda hari ini', now_jkt=ref_now), date(2026, 10, 28))
        self.assertEqual(parse_agenda_date('simetri-agenda', now_jkt=ref_now), date(2026, 10, 28))
        # Besok
        self.assertEqual(parse_agenda_date('simetri-agenda besok', now_jkt=ref_now), date(2026, 10, 29))
        # Tanggal YYYY-MM-DD
        self.assertEqual(
            parse_agenda_date('simetri-agenda tanggal 2026-10-29', now_jkt=ref_now),
            date(2026, 10, 29),
        )
        # Tanggal DD-MM-YYYY
        self.assertEqual(
            parse_agenda_date('simetri-agenda tanggal 29-10-2026', now_jkt=ref_now),
            date(2026, 10, 29),
        )
        # Tanggal DD/MM/YYYY
        self.assertEqual(
            parse_agenda_date('simetri-agenda 29/10/2026', now_jkt=ref_now),
            date(2026, 10, 29),
        )
        # Tanggal nama bulan
        self.assertEqual(
            parse_agenda_date('simetri-agenda tanggal 29 Oktober 2026', now_jkt=ref_now),
            date(2026, 10, 29),
        )

        # Invalid date
        with self.assertRaises(ValueError):
            parse_agenda_date('simetri-agenda tanggal 99-99-9999', now_jkt=ref_now)

    def test_handle_agenda_service(self):
        ref_now = datetime(2026, 10, 28, 8, 0, 0)

        # 1. Successful query with results (2026-10-29)
        res = handle_whatsapp_agenda(
            'simetri-agenda tanggal 2026-10-29',
            self.user,
            self.session,
            now_jkt=ref_now,
        )
        self.assertEqual(res['status'], 'success')
        self.assertEqual(res['count'], 2)
        self.assertIn('Rapat Koordinasi Teknis RKPD 2027', res['reply'])
        self.assertIn('Musrenbang Kecamatan Tegal Barat', res['reply'])
        self.assertNotIn('<p>', res['reply'], 'HTML tags should be stripped')

        # 2. Query with DD-MM-YYYY format
        res2 = handle_whatsapp_agenda(
            'simetri-agenda tanggal 29-10-2026',
            self.user,
            self.session,
            now_jkt=ref_now,
        )
        self.assertEqual(res2['status'], 'success')
        self.assertEqual(res2['count'], 2)

        # 3. Query on date with no agenda
        res_empty = handle_whatsapp_agenda(
            'simetri-agenda tanggal 2026-10-31',
            self.user,
            self.session,
            now_jkt=ref_now,
        )
        self.assertEqual(res_empty['status'], 'success')
        self.assertEqual(res_empty['count'], 0)
        self.assertIn('Tidak ada agenda kegiatan', res_empty['reply'])

        # 4. Unauthorized user (inactive)
        res_unauth = handle_whatsapp_agenda(
            'simetri-agenda hari ini',
            self.inactive_user,
            self.session,
            now_jkt=ref_now,
        )
        self.assertEqual(res_unauth['status'], 'unauthorized')
        self.assertIn('DITOLAK', res_unauth['reply'])

    def test_webhook_integration(self):
        async def run_async_tests():
            app = FastAPI()
            app.include_router(whatsapp.router)

            whatsapp.PROCESSED_MESSAGE_IDS.clear()
            whatsapp.IN_FLIGHT_MESSAGES.clear()

            with patch.object(whatsapp, 'engine', self.engine), \
                 patch.object(whatsapp, 'get_user_by_whatsapp_phone', side_effect=lambda phone: get_user_by_whatsapp_phone(phone, self.session)), \
                 patch.object(whatsapp, 'append_to_file'), \
                 patch.object(whatsapp, 'send_whatsapp_message', new_callable=AsyncMock) as send_mock:

                send_mock.return_value = {'success': True, 'http_code': 200, 'response': '{"status":"ok"}', 'error': ''}

                async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
                    # 1. Registered user asks for agenda (simetri-agenda tanggal 2026-10-29)
                    payload_ok = {
                        'event': 'message',
                        'payload': {
                            'id': 'agenda-test-1',
                            'from': '6281234567890@s.whatsapp.net',
                            'body': 'simetri-agenda tanggal 2026-10-29',
                        },
                    }
                    resp = await client.post('/api/whatsapp', json=payload_ok)
                    self.assertEqual(resp.status_code, 200)
                    data = resp.json()
                    self.assertIn('agenda', data)
                    self.assertEqual(data['agenda']['status'], 'success')
                    self.assertEqual(data['agenda']['count'], 2)
                    self.assertTrue(send_mock.called)

                    # 2. Registered user with format DD-MM-YYYY
                    payload_ok2 = {
                        'event': 'message',
                        'payload': {
                            'id': 'agenda-test-2',
                            'from': '6281234567890@s.whatsapp.net',
                            'body': 'simetri-agenda tanggal 29-10-2026',
                        },
                    }
                    resp2 = await client.post('/api/whatsapp', json=payload_ok2)
                    self.assertEqual(resp2.status_code, 200)
                    self.assertEqual(resp2.json()['agenda']['status'], 'success')

                    # 3. Unregistered phone number
                    payload_denied = {
                        'event': 'message',
                        'payload': {
                            'id': 'agenda-test-3',
                            'from': '6289991112223@s.whatsapp.net',
                            'body': 'simetri-agenda hari ini',
                        },
                    }
                    resp_denied = await client.post('/api/whatsapp', json=payload_denied)
                    self.assertEqual(resp_denied.status_code, 200)
                    self.assertEqual(resp_denied.json()['agenda']['status'], 'unauthorized')

                    # 4. Group message ignored
                    payload_group = {
                        'event': 'message',
                        'payload': {
                            'id': 'agenda-test-4',
                            'from': '6281234567890@s.whatsapp.net',
                            'chat_id': '123456@g.us',
                            'is_group': True,
                            'body': 'simetri-agenda hari ini',
                        },
                    }
                    resp_group = await client.post('/api/whatsapp', json=payload_group)
                    self.assertEqual(resp_group.status_code, 200)
                    self.assertEqual(resp_group.json()['agenda']['status'], 'ignored_group')

        asyncio.run(run_async_tests())


if __name__ == '__main__':
    unittest.main()
