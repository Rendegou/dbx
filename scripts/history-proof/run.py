"""macOS native WKWebView A/B evidence for #10328; no Rust compilation.

Requires pnpm install and Pillow. Exit 0 = verified layout regression,
1 = candidate failure, 2 = reproduction/visual evidence inconclusive.
This is a frontend layout test, not a packaged Tauri integration test.
"""
import argparse
import hashlib
import json
import os
import platform
import queue
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPONENT = 'apps/desktop/src/components/editor/QueryHistory.vue'
BASELINE = 'e9b768285'

MEASURE = r"""(() => {
 const panel = document.querySelector('[data-history-panel]');
 const filter = panel?.querySelector('.history-filter-scroll');
 const search = panel?.querySelector('[data-history-search]');
 if (!filter || !search) return null;
 const rect = e => {const r = e.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,right:r.right};};
 const buttons = [...filter.querySelectorAll('button')];
 const last = buttons.at(-1);
 const f = rect(filter), s = rect(search);
 return {panel:rect(panel),filter:f,search:s,buttons:buttons.map(rect),
   labels:buttons.map(b=>b.textContent.trim()), locale:document.documentElement.lang,
   scrollLeft:filter.scrollLeft, clientWidth:filter.clientWidth, scrollWidth:filter.scrollWidth,
   lastVisible:rect(last).right <= f.right + 1,
   gap:s.y - Math.max(...buttons.map(b=>rect(b).bottom)),
   inputHit:document.elementFromPoint(s.x+s.width/2,s.y+s.height/2) === search,
   focused:document.activeElement === search, inputValue:search.value,
   wheelEvents:window.__historyWheels || [], frames:window.__historyFrames || []};
})()"""


def wait_for(fn, timeout=60):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            value = fn()
            if value:
                return value
        except (OSError, RuntimeError) as error:
            last = error
        time.sleep(0.1)
    raise TimeoutError(f'Condition not reached: {last}')


def stop(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class Host:
    def __init__(self, binary, directory):
        self.log = (directory / 'host.log').open('w')
        self.process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=self.log, text=True, bufsize=1)
        self.responses = queue.Queue()
        def read():
            for line in self.process.stdout:
                self.responses.put(line)
            self.responses.put(None)
        threading.Thread(target=read, daemon=True).start()

    def command(self, op, **kwargs):
        self.process.stdin.write(json.dumps(dict(op=op, **kwargs)) + '\n')
        self.process.stdin.flush()
        line = self.responses.get(timeout=30)
        if line is None:
            raise RuntimeError('Native host exited; see host.log')
        value = json.loads(line)['value']
        if isinstance(value, dict) and 'error' in value:
            raise RuntimeError(value['error'])
        return value

    def js(self, script):
        return self.command('eval', script=script)

    def rect(self, selector):
        return self.js(f"(() => {{const r=document.querySelector({json.dumps(selector)})?.getBoundingClientRect();return r?{{x:r.x,y:r.y,width:r.width,height:r.height}}:null;}})()")

    def click(self, selector):
        r = wait_for(lambda: self.rect(selector))
        self.command('click', x=r['x']+r['width']/2, y=r['y']+r['height']/2)

    def close(self):
        stop(self.process)
        self.log.close()


def screenshot(host, path):
    # Capture the compositor window, including native scrollbar layers.
    info = host.command('info')
    subprocess.run(['screencapture', '-x', '-o', '-l', str(info['window']), str(path)], check=True, timeout=10)
    from PIL import Image
    with Image.open(path) as im:
        if im.width < 500 or im.height < 400 or im.convert('L').getextrema()[0] == im.convert('L').getextrema()[1]:
            raise RuntimeError('Blank or invalid system screenshot')
    return info


def thumb_evidence(path, measurement, info):
    """Conservative pixel gate, not an assertion that arbitrary grey pixels are a thumb.

    Only inspect the empty strip strictly between filter labels and search input.
    Retain all raw images; require a movable horizontal segment across scroll states.
    """
    from PIL import Image
    with Image.open(path) as source:
        im = source.convert('RGB')
        scale = im.width / info['width']
        title = im.height - info['height'] * scale
        f, s = measurement['filter'], measurement['search']
        y0 = int(title + (max(b['bottom'] for b in measurement['buttons'])+1) * scale)
        y1 = int(title + (s['y']-1)*scale)
        x0, x1 = int((f['x']+12)*scale), int((f['right']-12)*scale)
        segments = []
        for y in range(max(0,y0), min(im.height,y1)):
            start = None
            for x in range(max(0,x0), min(im.width,x1)+1):
                rgb = im.getpixel((x,y)) if x < min(im.width,x1) else (255,255,255)
                ink = max(rgb)-min(rgb) < 20 and 45 < sum(rgb)/3 < 235
                if ink and start is None:
                    start = x
                elif not ink and start is not None:
                    if 24*scale <= x-start <= (x1-x0)*0.9:
                        segments.append({'x':start/scale, 'end':x/scale, 'y':(y-title)/scale})
                    start = None
        return segments


def moving_thumb(shots):
    # Compare distinct frames and predict thumb travel from native scrollLeft.
    # Static borders, two unrelated lines in one image, and scrolling label text
    # must not satisfy this gate.
    for i, first in enumerate(shots):
        a = first['layout']
        for second in shots[i+1:]:
            b = second['layout']
            delta = b['scrollLeft'] - a['scrollLeft']
            expected = delta * a['clientWidth'] / a['scrollWidth']
            if abs(expected) < 10:
                continue
            expected_length = a['clientWidth'] ** 2 / a['scrollWidth']
            for left in first['thumbSegments']:
                length = left['end'] - left['x']
                if not 0.65 * expected_length <= length <= 1.25 * expected_length:
                    continue
                for right in second['thumbSegments']:
                    # Reject static segments present in both images, including
                    # two fixed borders separated by the expected travel.
                    if any(abs(left['x']-s['x']) <= 2 and abs(left['end']-s['end']) <= 2 and abs(left['y']-s['y']) <= 1 for s in second['thumbSegments']):
                        continue
                    if any(abs(right['x']-s['x']) <= 2 and abs(right['end']-s['end']) <= 2 and abs(right['y']-s['y']) <= 1 for s in first['thumbSegments']):
                        continue
                    if (abs(left['y']-right['y']) <= 1 and
                        abs(length-(right['end']-right['x'])) <= 5 and
                        abs((right['x']-left['x'])-expected) <= 6):
                        return {'from':first['file'], 'to':second['file'],
                                'expectedTravel':expected, 'observedTravel':right['x']-left['x']}
    return None


def exercise(host, directory, widths):
    toolbar = 'button:has(svg.lucide-history)'
    wait_for(lambda: host.rect(toolbar), 120)
    host.js("window.__inputTrace=[];['pointerdown','pointerup','click','wheel'].forEach(type=>document.addEventListener(type,e=>window.__inputTrace.push({type:e.type,x:e.clientX,y:e.clientY,trusted:e.isTrusted,target:e.target.tagName}),true));true")
    host.click(toolbar)
    wait_for(lambda: host.js(MEASURE))
    result = {'cases': [], 'nativeHost': host.command('info')}
    for width in widths:
        case = {'width': width, 'cycles': []}
        result['cases'].append(case)
        for cycle in range(3):
            label = f'{width}-{cycle}'
            m = host.js(MEASURE)
            # Use the app's actual resize handle and trusted pointer events.
            handle = host.rect('[data-history-panel]')
            x, y = handle['x'], handle['y'] + 120
            host.command('down', x=x, y=y)
            target = x + m['panel']['width'] - width
            for step in range(1, 9):
                host.command('drag', x=x+(target-x)*step/8, y=y)
                time.sleep(0.03)
            host.command('up', x=target, y=y)
            wait_for(lambda: abs(host.js(MEASURE)['panel']['width']-width) < 3)
            host.js("window.__historyWheels=[];window.__historyFrames=[];window.__historySampling=true;document.querySelector('.history-filter-scroll').addEventListener('wheel',e=>window.__historyWheels.push({trusted:e.isTrusted,dx:e.deltaX}),{passive:true});(function sample(){if(!window.__historySampling)return;const f=document.querySelector('.history-filter-scroll'),s=document.querySelector('[data-history-search]');if(f&&s)window.__historyFrames.push({searchTop:s.getBoundingClientRect().top,filterBottom:f.getBoundingClientRect().bottom,scrollLeft:f.scrollLeft});requestAnimationFrame(sample)})();true")
            before = host.js(MEASURE)
            if before['labels'] != ['All', 'Queries', 'Data changes', 'Schema changes', 'Failed']:
                raise RuntimeError(f"Unexpected language/filters: {before['labels']}")
            overflowing = before['scrollWidth'] > before['clientWidth'] + 3
            shots = []
            def capture(name):
                measurement = host.js(MEASURE)
                filename = f'{label}-{name}.png'
                info = screenshot(host, directory / filename)
                shots.append({'file':filename, 'layout':measurement,
                              'thumbSegments':thumb_evidence(directory/filename,measurement,info)})
            f = before['filter']
            px, py = f['x']+f['width']/2, f['bottom']-3
            host.command('move', x=px, y=py)
            time.sleep(0.15)
            capture('hover')
            # Scroll right and then back; capture during native scrolling, not after fade-out.
            for direction, delta in [('right', -35), ('left', 35)]:
                for tick in range(10):
                    host.command('wheel', x=px, y=f['y']+16, delta=delta)
                    time.sleep(0.035)
                    if tick in (1, 5, 9):
                        capture(f'{direction}-{tick}')
            after = host.js(MEASURE)
            host.click('[data-history-search]')
            focused = wait_for(lambda: host.js(MEASURE)['focused'])
            host.js('window.__historySampling=false;true')
            frames = after['frames']
            motion = max(v['scrollLeft'] for v in frames)-min(v['scrollLeft'] for v in frames)
            jitter = max(v['searchTop'] for v in frames)-min(v['searchTop'] for v in frames)
            visual = moving_thumb(shots)
            entry = {'overflow':overflowing, 'scrollMotion':motion, 'searchJitter':jitter,
                     'nativeWheelReceived':any(e['trusted'] and abs(e['dx'])>0 for e in after['wheelEvents']),
                     'searchUsable':focused and all(s['layout']['inputHit'] for s in shots),
                     'lastFilterReached':any(s['layout']['lastVisible'] for s in shots),
                     'minGap':min(s['layout']['gap'] for s in shots),
                     'movingThumbVisible':bool(visual), 'thumbMatch':visual, 'screenshots':shots}
            # 8px is the user-visible clearance contract, independent of the 44px implementation.
            entry['layoutPass'] = entry['searchUsable'] and jitter <= 1 and (not overflowing or entry['minGap'] >= 8)
            entry['inputPass'] = not overflowing or (motion > 10 and entry['nativeWheelReceived'] and entry['lastFilterReached'])
            case['cycles'].append(entry)
            (directory/'partial.json').write_text(json.dumps(result,indent=2))
            host.click(toolbar)
            wait_for(lambda: host.js("document.querySelector('[data-history-panel]') === null"))
            host.click(toolbar)
            wait_for(lambda: host.js(MEASURE))
    return result


def verdict(baseline, candidate, require_reproduction=True):
    old = [c for case in baseline['cases'] for c in case['cycles']]
    new = [c for case in candidate['cases'] for c in case['cycles']]
    if not new or not all(c['inputPass'] for c in old+new):
        return 2, 'INCONCLUSIVE: native input did not reproduce horizontal scrolling'
    if not all(c['layoutPass'] for c in new):
        return 1, 'FAIL: candidate violates search clearance/stability/usability'
    if not all(c['movingThumbVisible'] for c in new if c['overflow']):
        return 2, 'INCONCLUSIVE: layout passed, but native scrollbar pixels were not proven visible'
    if not require_reproduction:
        return 0, 'CONTROL PASS: candidate layout and native scrollbar work; this mode does not establish baseline reproduction'
    if not any(c['overflow'] and c['minGap'] < 8 and c['movingThumbVisible'] for c in old):
        return 2, 'INCONCLUSIVE: baseline clearance failure with a visible moving scrollbar was not reproduced'
    return 0, 'PASS: A/B clearance regression with native scroll and visible moving thumb (review raw images for original video equivalence)'


def make_gallery(output, results):
    from PIL import Image, ImageDraw
    panels = []
    for variant in ['baseline', 'candidate']:
        cycles = results.get(variant, {}).get('cases', [])
        if not cycles:
            continue
        shots = cycles[0]['cycles'][0]['screenshots']
        for shot in [shots[0], shots[2], shots[5]]:
            im = Image.open(output/variant/shot['file']).convert('RGB')
            # Keep raw screenshots separate; labels only appear on this contact sheet.
            im.thumbnail((550, 420))
            panel = Image.new('RGB',(550,460),'white')
            panel.paste(im,(0,40))
            ImageDraw.Draw(panel).text((8,8),f"{variant}: {shot['file']}",fill='black')
            panels.append(panel)
    if panels:
        sheet = Image.new('RGB',(1650,920),'#e4e4e4')
        for i,panel in enumerate(panels):
            sheet.paste(panel,((i%3)*550,(i//3)*460))
        sheet.save(output/'comparison.png')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'history-proof-results')
    parser.add_argument('--baseline', default=BASELINE)
    parser.add_argument('--widths', default='288,240,600')
    parser.add_argument('--theme', choices=['dark','light'], default='dark')
    parser.add_argument('--control-only', action='store_true', help='Compatibility control; never claims baseline reproduction')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Run this native test on macOS; use the GitHub workflow from Windows.')
    output = args.output.resolve()
    os.environ['HISTORY_THEME'] = args.theme
    output.mkdir(parents=True,exist_ok=True)
    results = {'scope':'Real app frontend in native WKWebView, mocked external APIs; not packaged Tauri',
               'os':platform.platform(), 'theme':args.theme, 'controlOnly':args.control_only,
               'scrollbarPreference':subprocess.check_output(['defaults','read','-g','AppleShowScrollBars'],text=True).strip(),
               'startedAt':time.time(), 'baselineRef':args.baseline,
               'candidateSha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
    binary = output/'history-host'
    subprocess.run(['swiftc',str(Path(__file__).with_name('Host.swift')),'-o',str(binary),'-framework','AppKit','-framework','WebKit'],check=True)
    baseline = subprocess.check_output(['git','show',f'{args.baseline}:{COMPONENT}'],cwd=ROOT)
    baseline_file = output/'baseline.vue'
    baseline_file.write_bytes(baseline)
    results['componentHashes'] = { 'baseline':hashlib.sha256(baseline).hexdigest(),
        'candidate':hashlib.sha256((ROOT/COMPONENT).read_bytes()).hexdigest() }
    code = 2
    try:
        for variant in ['baseline','candidate']:
            directory = output/variant
            directory.mkdir(exist_ok=True)
            env = os.environ.copy()
            env.pop('TAURI_ENV_ARCH',None)
            env.pop('TAURI_DEV_HOST',None)
            env.pop('HISTORY_BASELINE_FILE',None)
            if variant == 'baseline':
                env['HISTORY_BASELINE_FILE'] = str(baseline_file)
            server = host = None
            with (directory/'vite.log').open('w') as log:
                try:
                    server = subprocess.Popen(['node','node_modules/vite/bin/vite.js','--config','scripts/history-proof/vite.config.mjs','--mode','web','--port','5198'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                    wait_for(lambda: urllib.request.urlopen('http://127.0.0.1:5198',timeout=2).status == 200)
                    host = Host(binary,directory)
                    host.command('load',url='http://127.0.0.1:5198')
                    results[variant] = exercise(host,directory,[int(w) for w in args.widths.split(',')])
                except Exception:
                    if host:
                        try:
                            screenshot(host, directory/'failure.png')
                            state = host.js("({url:location.href,text:document.body.innerText,events:window.__inputTrace,html:document.body.innerHTML.slice(0,5000)})")
                            state['nativeHost'] = host.command('info')
                            (directory/'failure-state.json').write_text(json.dumps(state,indent=2))
                        except Exception as capture_error:
                            (directory/'failure-capture.log').write_text(repr(capture_error))
                    raise
                finally:
                    if host:
                        host.close()
                    stop(server)
        code, results['verdict'] = verdict(results['baseline'],results['candidate'],not args.control_only)
        make_gallery(output,results)
    except Exception as error:
        results['verdict'] = f'INCONCLUSIVE: harness/environment failure: {error!r}'
        import traceback
        results['errorTraceback'] = traceback.format_exc()
    finally:
        results['durationSeconds'] = round(time.time()-results['startedAt'],2)
        (output/'result.json').write_text(json.dumps(results,indent=2))
        print(results.get('verdict','INCONCLUSIVE'),flush=True)
    return code


if __name__ == '__main__':
    sys.exit(main())
