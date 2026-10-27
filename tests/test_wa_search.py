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
from app.models.surat import Surat
from app.models.dokumen import DokumenPerencanaan
from app.models.kejadian import Kejadian
from app.services.wa_archive_service import get_user_by_whatsapp_phone
from app.services.wa_search_service import is_search_request, parse_search_query, search_whatsapp
from app.routers import whatsapp


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False})
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.user = User(email='active@example.test', name='Pengguna', no_hp='081234567890', role='admin')
        self.session.add(self.user)
        self.session.add(User(email='inactive@example.test', no_hp='089999999999', is_active=False))
        for ident, opd_id, active in [(1,None,True),(2,10,True),(3,20,True),(4,None,False)]:
            self.session.add(DokumenPerencanaan(id=ident,nama=f'RKPD {ident}',jenis='RKPD',opd_id=opd_id,is_active=active))
            self.session.add(Kejadian(id=ident,dokumen_id=ident,tanggal_kejadian=datetime(2026,10,27),jenis_kejadian='Rapat',judul_kejadian=f'Rapat RKPD {ident}',uraian_kronologi='<p>Pembahasan pembangunan</p>'))
        self.session.add(Surat(jenis_surat='Surat Masuk',nomor_surat='001/RKPD',tanggal_surat=date(2026,10,27),pihak='Bappeda',perihal='Rapat RKPD'))
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_parser(self):
        for text in ['simetri-cari "rapat RKPD"','SIMETRI-CARI rapat RKPD','simetri-cari “rapat RKPD”']:
            self.assertEqual(parse_search_query(text),'rapat RKPD')
        for text in ['simetri-cari','simetri-cari ""','simetri-cari "belum ditutup','simetri-cari '+('a'*201)]:
            with self.assertRaises(ValueError): parse_search_query(text)
        self.assertFalse(is_search_request('simetri rkpd rapat'))
        self.assertFalse(is_search_request('simetri-carikan rapat'))

    def test_phone_access(self):
        for phone in ['+6281234567890','0812-3456-7890','6281234567890@s.whatsapp.net']:
            self.assertEqual(get_user_by_whatsapp_phone(phone,self.session).id,self.user.id)
        for phone in ['089999999999','9991234567890','', '081111111111']:
            self.assertIsNone(get_user_by_whatsapp_phone(phone,self.session))

    def test_results_roles_and_literal_search(self):
        result=search_whatsapp('simetri-cari "RKPD"',self.user,self.session)
        self.assertEqual((result['arsip_count'],result['kejadian_count']),(1,3))
        self.assertNotIn('<p>',result['reply'])
        for role,opd_id,count in [('user_bidang',None,1),('user_opd',10,1),('user_opd',None,0),('user_opd',99,0)]:
            user=User(email='role@example.test',role=role,opd_id=opd_id)
            result=search_whatsapp('simetri-cari RKPD',user,self.session)
            self.assertEqual(result['kejadian_count'],count)
        for query in ['%','_',"' OR 1=1 --",'tidak ditemukan']:
            result=search_whatsapp('simetri-cari '+chr(34)+query+chr(34),self.user,self.session)
            self.assertEqual(result['arsip_count'],0)
            self.assertEqual(result['kejadian_count'],0)
        self.assertEqual(search_whatsapp('simetri-cari RKPD',User(email='x',is_active=False),self.session)['status'],'unauthorized')

    def test_limit(self):
        for i in range(8):
            self.session.add(Surat(jenis_surat='Surat Masuk',nomor_surat=str(i),tanggal_surat=date(2026,10,27),pihak='Bappeda',perihal='RKPD'))
        self.session.commit()
        result=search_whatsapp('simetri-cari RKPD',self.user,self.session)
        self.assertEqual(result['arsip_count'],5)
        self.assertIn('maksimal 5',result['reply'])

    def test_webhook_dispatch(self):
        app=FastAPI();app.include_router(whatsapp.router)
        async def run():
            whatsapp.PROCESSED_MESSAGE_IDS.clear();whatsapp.IN_FLIGHT_MESSAGES.clear()
            with patch.object(whatsapp,'engine',self.engine), patch.object(whatsapp,'get_user_by_whatsapp_phone',side_effect=lambda phone:get_user_by_whatsapp_phone(phone,self.session)), patch.object(whatsapp,'append_to_file'), patch.object(whatsapp,'send_whatsapp_message',new_callable=AsyncMock) as send, patch.object(whatsapp,'get_active_archive') as active, patch.object(whatsapp,'pop_pending_archive_command') as pending, patch.object(whatsapp,'process_whatsapp_kejadian',new_callable=AsyncMock) as record:
                send.return_value={'success':True,'http_code':200}
                async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
                    payload={'event':'message','payload':{'id':'search-1','from':'6281234567890@s.whatsapp.net','body':'simetri-cari "RKPD"'}}
                    response=await client.post('/api/whatsapp',json=payload)
                    self.assertEqual(response.json()['search']['arsip_count'],1)
                    self.assertIn('HASIL PENCARIAN',send.call_args.args[1])
                    active.assert_not_called();pending.assert_not_called();record.assert_not_called()
                    duplicate=await client.post('/api/whatsapp',json=payload)
                    self.assertEqual(duplicate.json()['status'],'ignored')
                    self.assertEqual(send.await_count,1)
                    payload['payload'].update(id='search-2', **{'from':'6281111111111@s.whatsapp.net'})
                    denied=await client.post('/api/whatsapp',json=payload)
                    self.assertEqual(denied.json()['search']['status'],'unauthorized')
                    self.assertNotIn('RKPD',send.call_args.args[1])
                    payload['payload'].update(id='search-3', **{'from':'6281234567890@s.whatsapp.net','chat_id':'123@g.us'})
                    group=await client.post('/api/whatsapp',json=payload)
                    self.assertEqual(group.json()['search']['status'],'ignored_group')
                    self.assertEqual(send.await_count,2)
                    payload['payload'].update(id='search-4',chat_id='',body='simetri-cari')
                    invalid=await client.post('/api/whatsapp',json=payload)
                    self.assertEqual(invalid.json()['search']['status'],'invalid_query')
                    payload['payload'].update(id='search-5',body='simetri-cari RKPD')
                    with patch.object(whatsapp,'search_whatsapp',side_effect=RuntimeError('database unavailable')), patch.object(whatsapp.logger,'exception'):
                        failed=await client.post('/api/whatsapp',json=payload)
                    self.assertEqual(failed.json()['search']['status'],'error')
                    self.assertNotIn('database unavailable',send.call_args.args[1])
                    payload['payload'].update(id='search-6',is_from_me=True)
                    sent_before=send.await_count
                    await client.post('/api/whatsapp',json=payload)
                    self.assertEqual(send.await_count,sent_before)
        asyncio.run(run())


if __name__=='__main__':
    unittest.main()
