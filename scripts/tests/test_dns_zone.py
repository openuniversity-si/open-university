"""scripts/dns-zone (D-323 step 3): Cloudflare's BIND export -> the record list -> the Route 53 stack, and the offline compare.
Hermetic: a sample export with fake values (scripts/tests/fixtures/dns/cloudflare-export.zone), temporary files, no network.
"""
import contextlib
import io
import ipaddress
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts/lib'))
import dns_zone  # noqa: E402

FIXTURE = ROOT / 'scripts/tests/fixtures/dns/cloudflare-export.zone'
ZONE = 'openuniversity.si.'


def build(text=None, targets=None):
    text = FIXTURE.read_text(encoding='utf-8') if text is None else text
    return dns_zone.record_list(text, FIXTURE.name, ZONE, dns_zone.proxy_networks(), targets)


def created(template, **values):
    """The resources and outputs CloudFormation creates for these parameter values (the three conditions of the stack)."""
    params = {name: values.get(name, spec['Default']) for name, spec in template['Parameters'].items()}
    on = params['Zone'] == 'on'
    truth = {'ZoneOn': on, 'ZoneOff': not on, 'SiteKnown': on and params['SiteDistribution'] != ''}
    keep = lambda section: {name: item for name, item in template.get(section, {}).items()
                            if truth[item.get('Condition', 'ZoneOn')] or 'Condition' not in item}
    return keep('Resources'), keep('Outputs')


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = dns_zone.main(list(argv))
    return code, out.getvalue() + err.getvalue()


class RecordListTests(unittest.TestCase):
    def setUp(self):
        self.data = build()
        self.by = {(item['name'], item['type']): item for item in self.data['records']}

    def test_every_type_of_the_export_is_read_and_named_whole(self):
        self.assertEqual({rtype for _, rtype in self.by},
                         {'A', 'AAAA', 'CAA', 'CNAME', 'MX', 'NS', 'SRV', 'TXT'})
        self.assertTrue(all(name.endswith(ZONE) for name, _ in self.by))
        self.assertEqual(self.by[('legacy.openuniversity.si.', 'A')]['values'], ['192.0.2.10', '192.0.2.11'])
        self.assertEqual(self.by[('legacy.openuniversity.si.', 'AAAA')]['values'], ['2001:db8::10'])
        self.assertEqual(self.by[(ZONE, 'MX')]['values'], ['10 mx1.mail.example.org.', '20 mx2.mail.example.org.'])
        self.assertEqual(self.by[('_sip._tcp.openuniversity.si.', 'SRV')]['values'], ['10 60 5060 sip.example.org.'])
        self.assertEqual(self.by[(ZONE, 'CAA')]['values'],
                         ['0 iodef "mailto:security@example.org"', '0 issue "amazon.com"'])
        self.assertEqual(self.by[('lab.openuniversity.si.', 'NS')]['values'], ['ns1.example.net.'])

    def test_the_apex_ns_and_soa_are_dropped(self):
        self.assertEqual(self.data['dropped'], [f'{ZONE} NS', f'{ZONE} SOA'])
        self.assertNotIn((ZONE, 'NS'), self.by)
        self.assertFalse([key for key in self.by if key[1] == 'SOA'])

    def test_txt_strings_are_joined_and_quotes_inside_kept(self):
        self.assertEqual(self.by[('_dmarc.openuniversity.si.', 'TXT')]['values'],
                         ['v=DMARC1; p=quarantine; rua=mailto:dmarc@example.org'])
        self.assertEqual(self.by[('note.openuniversity.si.', 'TXT')]['values'], ['say "hi"; not a comment'])
        [dkim] = self.by[('selector1._domainkey.openuniversity.si.', 'TXT')]['values']
        self.assertGreater(len(dkim), 255)
        self.assertTrue(dkim.startswith('v=DKIM1; k=rsa; p=MIIB'))

    def test_cloudflare_s_automatic_ttl_is_300(self):
        self.assertEqual(self.by[('www.openuniversity.si.', 'CNAME')]['ttl'], 300)
        self.assertEqual(self.by[(ZONE, 'MX')]['ttl'], 3600)

    def test_a_proxied_record_is_refused_and_listed_with_its_reason(self):
        listed = {(item['name'], item['type']): item for item in self.data['needs_target']}
        self.assertEqual(set(listed), {('cdn.openuniversity.si.', 'A'), ('media.openuniversity.si.', 'CNAME')})
        self.assertIn('Cloudflare proxy address', listed[('cdn.openuniversity.si.', 'A')]['reason'])
        self.assertIn('cf-proxied:true', listed[('media.openuniversity.si.', 'CNAME')]['reason'])
        for key in listed:
            self.assertNotIn(key, self.by)
        body = dns_zone.render(self.data)
        self.assertNotIn('104.21.32.10', body)
        self.assertNotIn('r2.example.net', body)

    def test_a_proxy_address_is_refused_even_without_the_tag(self):
        text = '$ORIGIN openuniversity.si.\nedge 300 IN AAAA 2606:4700::6810:1\nplain 300 IN A 203.0.113.5\n'
        data = build(text)
        self.assertEqual([(item['name'], item['type']) for item in data['needs_target']],
                         [('edge.openuniversity.si.', 'AAAA')])
        self.assertEqual([item['name'] for item in data['records']], ['plain.openuniversity.si.'])

    def test_a_real_target_replaces_the_proxied_record(self):
        targets = {'media.openuniversity.si. CNAME': {'type': 'CNAME', 'values': ['d222222abcdef8.cloudfront.net.'],
                                                      'ttl': 300}}
        data = build(targets=targets)
        [media] = [item for item in data['records'] if item['name'] == 'media.openuniversity.si.']
        self.assertEqual(media['values'], ['d222222abcdef8.cloudfront.net.'])
        self.assertIn('cf-proxied:true', media['replaces'])
        self.assertEqual([item['name'] for item in data['needs_target']], ['cdn.openuniversity.si.'])

    def test_the_proxy_ranges_come_from_the_checked_in_list_with_its_source(self):
        listed = json.loads(dns_zone.PROXY_IPS.read_text(encoding='utf-8'))
        self.assertEqual([source.rsplit('/', 1)[1] for source in listed['sources']], ['ips-v4', 'ips-v6'])
        self.assertTrue(all(source.startswith('https://') and 'cloudflare.com' in source for source in listed['sources']))
        self.assertIn('refresh', listed['about'])
        networks = dns_zone.proxy_networks()
        self.assertEqual(len(networks), len(listed['ipv4']) + len(listed['ipv6']))
        self.assertFalse(re.search(r'\d+\.\d+\.\d+\.\d+/\d+', (ROOT / 'scripts/lib/dns_zone.py').read_text()))
        self.assertTrue(any(ipaddress.ip_address('104.21.32.10') in net for net in networks))

    def test_what_route_53_cannot_hold_is_an_error(self):
        cases = {
            '$ORIGIN openuniversity.si.\na 300 IN A 192.0.2.1\na 300 IN CNAME b.example.org.\n': 'a CNAME stands alone',
            '$ORIGIN openuniversity.si.\na 300 IN A 192.0.2.1\na 600 IN A 192.0.2.2\n': 'one TTL per set',
            '$ORIGIN openuniversity.si.\na 300 IN LOC 52 22 23.000 N 4 53 32.000 E -2.00m\n': 'not one Route 53 serves',
            '$ORIGIN openuniversity.si.\na IN A 192.0.2.1\n': 'no TTL',
            '$ORIGIN openuniversity.si.\na 300 IN TXT "open\n': 'not closed',
        }
        for text, message in cases.items():
            with self.assertRaises(dns_zone.ZoneError, msg=text) as caught:
                build(text)
            self.assertIn(message, str(caught.exception))

    def test_an_apex_cname_off_cloudfront_needs_its_target(self):
        data = build('$ORIGIN openuniversity.si.\n@ 300 IN CNAME site.example.org.\n')
        self.assertEqual(data['records'], [])
        self.assertIn('alias to an AWS target', data['needs_target'][0]['reason'])


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.data = build()
        self.template = json.loads(dns_zone.render(self.data))

    def test_one_record_set_per_name_and_type_and_the_apex_cname_is_an_alias(self):
        resources, _ = created(self.template, Zone='on', SiteDistribution='d111111abcdef8.cloudfront.net')
        sets = [item['Properties'] for item in resources.values() if item['Type'] == 'AWS::Route53::RecordSet']
        keys = [(item['Name'], item['Type']) for item in sets]
        self.assertEqual(len(keys), len(set(keys)))
        expected = {(item['name'], item['type']) for item in self.data['records']} - {(ZONE, 'CNAME')}
        self.assertEqual(set(keys), expected | {(ZONE, 'A'), (ZONE, 'AAAA')})
        for item in sets:
            self.assertEqual(item['HostedZoneId'], {'Ref': 'Zone'})
            if item['Name'] == ZONE and item['Type'] in ('A', 'AAAA'):
                self.assertEqual(item['AliasTarget'], {'DNSName': {'Ref': 'SiteDistribution'},
                                                       'HostedZoneId': 'Z2FDTNDATAQYW2', 'EvaluateTargetHealth': False})
                self.assertNotIn('TTL', item)
            else:
                self.assertNotIn('AliasTarget', item)
                self.assertTrue(item['TTL'].isdigit())
        www = next(item for item in sets if item['Name'] == 'www.openuniversity.si.')
        self.assertEqual((www['Type'], www['ResourceRecords']), ('CNAME', ['d111111abcdef8.cloudfront.net.']))

    def test_the_alias_waits_for_its_target(self):
        resources, _ = created(self.template, Zone='on')
        self.assertFalse([item for item in resources.values()
                          if item['Type'] == 'AWS::Route53::RecordSet' and item['Properties']['Name'] == ZONE
                          and item['Properties']['Type'] in ('A', 'AAAA')])
        pattern = re.compile(self.template['Parameters']['SiteDistribution']['AllowedPattern'])
        self.assertTrue(pattern.fullmatch('') and pattern.fullmatch('d111111abcdef8.cloudfront.net'))
        self.assertIsNone(pattern.fullmatch('openuniversity.si'))

    def test_txt_is_quoted_and_split_at_255(self):
        resources, _ = created(self.template, Zone='on')
        dkim = next(item['Properties'] for item in resources.values()
                    if item['Properties'].get('Name') == 'selector1._domainkey.openuniversity.si.')
        [value] = dkim['ResourceRecords']
        strings = re.findall(r'"((?:[^"\\]|\\.)*)"', value)
        self.assertGreater(len(strings), 1)
        self.assertTrue(all(len(item) <= 255 for item in strings))
        self.assertEqual(''.join(strings), self.data['records'][
            [item['name'] for item in self.data['records']].index('selector1._domainkey.openuniversity.si.')]['values'][0])
        note = next(item['Properties'] for item in resources.values()
                    if item['Properties'].get('Name') == 'note.openuniversity.si.')
        self.assertEqual(note['ResourceRecords'], ['"say \\"hi\\"; not a comment"'])
        spf = next(item['Properties'] for item in resources.values()
                   if item['Properties'].get('Name') == ZONE and item['Properties'].get('Type') == 'TXT')
        self.assertEqual(spf['ResourceRecords'],
                         ['"google-site-verification=abc123-DEF456_ghi789"', '"v=spf1 include:_spf.example.org ~all"'])
        self.assertEqual(dns_zone.txt_value('é'), '"\\195\\169"')

    def test_logical_ids_are_alphanumeric_and_unique(self):
        for name in self.template['Resources']:
            self.assertRegex(name, r'^[A-Za-z0-9]+$')
        taken = set()
        first = dns_zone.logical_id({'name': 'a-b.openuniversity.si.', 'type': 'A'}, ZONE, taken)
        second = dns_zone.logical_id({'name': 'ab.openuniversity.si.', 'type': 'A'}, ZONE, taken)
        self.assertNotEqual(first, second)

    def test_an_empty_record_list_is_the_zone_alone_or_nothing_that_bills(self):
        empty = json.loads(dns_zone.render({'zone': ZONE, 'records': [], 'needs_target': []}))
        on, outputs = created(empty, Zone='on')
        self.assertEqual(list(on), ['Zone'])
        self.assertEqual(on['Zone']['Properties']['Name'], ZONE)
        self.assertEqual(sorted(outputs), ['NameServers', 'ZoneId'])
        self.assertEqual(outputs['NameServers']['Value'], {'Fn::Join': [',', {'Fn::GetAtt': ['Zone', 'NameServers']}]})
        off, outputs = created(empty)
        self.assertEqual({name: item['Type'] for name, item in off.items()},
                         {'Pending': 'AWS::CloudFormation::WaitConditionHandle'})
        self.assertEqual(outputs, {})
        # the record sets of a full list are all behind Zone on
        off, _ = created(self.template)
        self.assertEqual(list(off), ['Pending'])

    def test_the_committed_stack_is_the_one_of_the_committed_list(self):
        data = json.loads(dns_zone.default_list().read_text(encoding='utf-8'))
        self.assertEqual(dns_zone.STACK.read_text(encoding='utf-8'), dns_zone.render(data),
                         'infra/aws/stacks/70-dns.json drifted from infra/aws/dns: run scripts/dns-zone template')
        code, out = run('template', '--check')
        self.assertEqual(code, 0, out)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.list, self.stack = self.tmp / 'list.json', self.tmp / 'stack.json'
        self.files = ['--list', str(self.list), '--stack', str(self.stack), '--targets', str(self.tmp / 'targets.json')]
        code, out = run('build', str(FIXTURE), *self.files)
        self.assertEqual(code, 0, out)
        self.out = out

    def test_build_writes_both_and_names_what_needs_a_target(self):
        self.assertIn('needs its real target: cdn.openuniversity.si. A', self.out)
        self.assertIn('needs its real target: media.openuniversity.si. CNAME', self.out)
        self.assertIn('dns.SiteDistribution to d111111abcdef8.cloudfront.net', self.out)
        self.assertEqual(json.loads(self.stack.read_text()), dns_zone.template(json.loads(self.list.read_text())))

    def test_compare_passes_on_the_same_export(self):
        code, out = run('compare', str(FIXTURE), *self.files)
        self.assertEqual(code, 0, out)
        self.assertIn('needs its real target: media.openuniversity.si. CNAME', out)
        self.assertIn('2 needing their real target', out)

    def test_compare_fails_on_a_changed_ttl_a_changed_value_and_a_missing_record(self):
        text = FIXTURE.read_text(encoding='utf-8')
        cases = {
            text.replace('_dmarc\t3600', '_dmarc\t600'): 'differs: _dmarc.openuniversity.si. TXT export ttl 600',
            text.replace('192.0.2.11', '192.0.2.12'): 'differs',
            text + 'new 300 IN A 198.51.100.7\n': 'missing from the record list',
            text.replace('lab\t3600\tIN\tNS\tns1.example.net.\n', ''): 'not in the export',
        }
        for changed, message in cases.items():
            export = self.tmp / 'changed.zone'
            export.write_text(changed, encoding='utf-8')
            code, out = run('compare', str(export), *self.files)
            self.assertEqual(code, 1, out)
            self.assertIn(message, out)

    def test_the_dig_plan_asks_every_record_of_the_route_53_servers(self):
        code, out = run('dig-plan', '--list', str(self.list), '--ns', 'ns-1.awsdns-01.org,ns-2.awsdns-02.net',
                        '--site', 'd111111abcdef8.cloudfront.net')
        self.assertEqual(code, 0, out)
        data = json.loads(self.list.read_text())
        for item in data['records']:
            if item['type'] != 'CNAME' or item['name'] != ZONE:
                self.assertIn(f"@ns-1.awsdns-01.org {item['name']} {item['type']} +short", out)
        self.assertIn(f'@ns-1.awsdns-01.org {ZONE} A +short  # expect the addresses of d111111abcdef8', out)
        self.assertIn(f'@ns-2.awsdns-02.net {ZONE} SOA', out)
        self.assertIn('not in Route 53 until its real target is known: cdn.openuniversity.si. A', out)

    def test_a_broken_export_is_exit_2_with_the_reason(self):
        export = self.tmp / 'broken.zone'
        export.write_text('$INCLUDE other.zone\n', encoding='utf-8')
        code, out = run('build', str(export), *self.files)
        self.assertEqual(code, 2)
        self.assertIn('$INCLUDE is not read here', out)


if __name__ == '__main__':
    unittest.main(verbosity=1)
