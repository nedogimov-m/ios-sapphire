"""Persistent address ownership, real native selection and exact overlay contract."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from ports.redfin import wifi_identity as identity
from ports.redfin.mkadt import build
from ports.redfin.test_usb_owned_route import added_file

HERE=Path(__file__).resolve().parent


class WifiIdentityTests(unittest.TestCase):
    def test_create_once_survives_fresh_loads_and_never_rotates_an_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'station.json'
            first=identity.create_local(path);before=path.read_bytes()
            self.assertEqual(os.stat(path).st_mode&0o777,0o600)
            self.assertEqual(identity.load(path),first)
            self.assertEqual(identity.create_local(path),first)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(len(identity.payload(first)),16)
            report=identity.report(path,first)
            self.assertTrue(report['persistent_station_address'])
            self.assertTrue(report['locally_administered'])
            self.assertFalse(report['factory_address'])
            self.assertFalse(report['identifier_logged'])
            self.assertNotIn('address_hex',report)
            path.chmod(0o644)
            with self.assertRaises(ValueError):identity.load(path)
            with self.assertRaises(ValueError):identity.create_local(path)
            path.chmod(0o600);path.write_text('{}')
            with self.assertRaises(ValueError):identity.create_local(path)
            self.assertEqual(path.read_text(),'{}')

    def test_invalid_multicast_zero_or_foreign_identity_is_never_encoded(self):
        good=dict(format_version=1,product='redfin',source='persistent-local',address_hex='020102030405')
        changes=[dict(format_version=True),dict(product='other'),dict(source='ephemeral'),
                 dict(address_hex='000000000000'),dict(address_hex='010102030405'),
                 dict(address_hex='000102030405'),dict(address_hex='0201020304'),
                 dict(address_hex='0201020304XX'),dict(secret='not allowed')]
        for change in changes:
            value=dict(good,**change)
            with self.subTest(change=change),self.assertRaises(ValueError):identity.payload(value)
        with tempfile.TemporaryDirectory() as directory:
            real=Path(directory)/'real';real.write_text(json.dumps(good));real.chmod(0o600)
            link=Path(directory)/'link';link.symlink_to(real)
            with self.assertRaises(ValueError):identity.load(link)
            with self.assertRaises(ValueError):identity.create_local(link)

    def test_private_ADT_property_changes_no_other_identity_or_hardware_contract(self):
        value=dict(format_version=1,product='redfin',source='persistent-local',address_hex='020102030405')
        tree=build(0x180000000,0x80000000,0,smp=True,smp_cpus=8)
        chosen=next(n for n in tree.children if n.name=='chosen')
        before=copy.deepcopy(chosen.props)
        identity.apply(tree,value)
        self.assertEqual(chosen.props[:-1],before)
        self.assertEqual(chosen.props[-1],(identity.PROPERTY,0,identity.payload(value)))
        with self.assertRaises(ValueError):identity.apply(tree,value)

    def test_actual_header_runtime_and_radio_selection_are_compiled_by_final_overlay(self):
        patch=(HERE/'native-wifi-station-identity.patch').read_text()
        for owned,native in [('wifi-identity.h','RedfinWiFiIdentity.h'),
                ('wifi-identity-runtime.inc','RedfinWiFiIdentity.inc'),
                ('wifi-station-address.inc','RedfinWiFiStationAddress.inc')]:
            self.assertEqual((HERE/owned).read_text(),added_file(patch,'iokit/Kernel/arm/'+native))

    def test_native_private_identity_consumption_and_station_choice_across_reboots(self):
        source=r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cerrno>
#include "wifi-identity.h"
struct OSObject{virtual ~OSObject()=default;};
struct OSData:OSObject{
 unsigned refs=1;unsigned char bytes[16]={};size_t length=16;
 void retain(){++refs;}void release(){assert(refs>1);--refs;}
 const void *getBytesNoCopy(){return bytes;}size_t getLength(){return length;}
};
static OSData data;static OSObject other;static bool chosen_present=true,property_present=true,wrong_type=false,removal_fails=false;
static unsigned removals,releases,random_calls,log_calls;
struct IORegistryEntry{
 static IORegistryEntry *fromPath(const char *path);
 OSObject *getProperty(const char *name){assert(!strcmp(name,RF_WIFI_IDENTITY_PROPERTY));return property_present?(wrong_type?&other:&data):nullptr;}
 void removeProperty(const char *name){assert(!strcmp(name,RF_WIFI_IDENTITY_PROPERTY));++removals;if(!removal_fails)property_present=false;}
 void release(){++releases;}
};
static IORegistryEntry chosen;
IORegistryEntry *IORegistryEntry::fromPath(const char *path){assert(!strcmp(path,"IODeviceTree:/chosen"));return chosen_present?&chosen:nullptr;}
#define OSDynamicCast(type,value) dynamic_cast<type *>(value)
static void IOLog(const char *,...){++log_calls;}
#include "wifi-identity-runtime.inc"
static int rf_radio_error;
static bool redfin_wifi_mac_usable(const uint8_t *a){return a&&!(a[0]&1)&&(a[0]|a[1]|a[2]|a[3]|a[4]|a[5]);}
static void read_random(void *memory,unsigned bytes){assert(bytes==6);memset(memory,(int)++random_calls,6);}
#define LOG(...) do{++log_calls;}while(0)
#include "wifi-station-address.inc"
static void reset(){
 redfin_station_identity_attempted=false;redfin_station_identity_source=0;memset(redfin_station_identity,0,6);
 chosen_present=property_present=true;wrong_type=removal_fails=false;removals=releases=random_calls=log_calls=0;rf_radio_error=0;
 memset(data.bytes,0,16);data.bytes[0]=1;data.bytes[4]=2;data.bytes[8]=2;data.bytes[9]=0x11;data.bytes[13]=0x22;data.refs=1;data.length=16;
}
int main(){
 uint8_t address[6],firmware[6]={},expected[6]={2,0x11,0,0,0,0x22};
 for(unsigned boot=0;boot<3;++boot){
  reset();memset(address,0xa5,6);assert(redfin_radio_select_station(address,firmware));
  assert(!memcmp(address,expected,6)&&!random_calls&&removals==1&&releases==1&&data.refs==1);
  assert(!property_present&&redfin_station_identity_source==2);
  assert(redfin_radio_select_station(address,firmware)&&!memcmp(address,expected,6)&&removals==1&&!random_calls);
 }
 reset();data.bytes[4]=1;data.bytes[8]=0x10;assert(RedfinWiFiCopyStationAddress(address)==1&&address[0]==0x10);
 for(unsigned scenario=0;scenario<6;++scenario){
  reset();memset(address,0xa5,6);
  if(scenario==0)data.bytes[0]=2;
  if(scenario==1)data.bytes[14]=1;
  if(scenario==2)data.bytes[8]|=1;
  if(scenario==3)data.length=15;
  if(scenario==4)wrong_type=true;
  if(scenario==5)removal_fails=true;
  assert(!redfin_radio_select_station(address,firmware)&&rf_radio_error==EINVAL&&!random_calls);
  for(unsigned i=0;i<6;++i)assert(address[i]==0xa5);
  assert(data.refs==1);
 }
 // A malformed packet never changes its destination, even for validation-only callers.
 reset();uint8_t copy[6];memset(copy,0xa5,6);data.bytes[5]=1;
 assert(!rf_wifi_identity_decode(data.bytes,16,copy)&&!rf_wifi_identity_decode(data.bytes,16,nullptr));
 for(auto b:copy)assert(b==0xa5);
 // Legacy diagnostic images without an identity retain their original firmware/random paths.
 reset();property_present=false;firmware[0]=0x10;firmware[1]=1;
 assert(redfin_radio_select_station(address,firmware)&&!memcmp(address,firmware,6)&&!random_calls);
 reset();property_present=false;memset(firmware,0,6);
 assert(redfin_radio_select_station(address,firmware)&&random_calls==1&&(address[0]&3)==2);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'identity.cpp';path.write_text(source)
            built=subprocess.run(['c++','-std=c++17','-O2','-Wall','-Wextra','-Werror',
                '-I'+str(HERE),str(path),'-o',str(root/'identity')],capture_output=True,text=True)
            self.assertEqual(built.returncode,0,built.stderr)
            ran=subprocess.run([str(root/'identity')],capture_output=True,text=True,timeout=10)
            self.assertEqual(ran.returncode,0,ran.stderr)


if __name__=='__main__':unittest.main()
