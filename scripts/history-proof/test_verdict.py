"""The evidence gate must reject incomplete or misleading runs."""
import copy
import unittest
import tempfile
from pathlib import Path
from run import moving_thumb, thumb_evidence, verdict


def report(gap=16):
    return {'cases':[{'cycles':[dict(inputPass=True, layoutPass=gap >= 8,
        overflow=True, minGap=gap, movingThumbVisible=True, thumbClearOfControls=gap>=8)]}]}


class EvidenceTests(unittest.TestCase):
    def test_baseline_must_fail_clearance_with_visible_thumb(self):
        self.assertEqual(verdict(report(6),report())[0],0)
        self.assertEqual(verdict(report(),report())[0],2)
        old = report(6)
        old['cases'][0]['cycles'][0]['movingThumbVisible'] = False
        self.assertEqual(verdict(old,report())[0],2)

    def test_candidate_failure_and_missing_input_never_pass(self):
        self.assertEqual(verdict(report(6),report(6))[0],1)
        new = report()
        new['cases'][0]['cycles'][0]['inputPass'] = False
        self.assertEqual(verdict(report(6),new)[0],2)
        new = report()
        new['cases'][0]['cycles'][0]['movingThumbVisible'] = False
        self.assertEqual(verdict(report(6),new)[0],2)

    def test_control_pass_is_explicit_and_never_reproduction(self):
        code, message = verdict(report(),report(),require_reproduction=False)
        self.assertEqual(code,0)
        self.assertTrue(message.startswith('CONTROL PASS'))
        self.assertEqual(verdict(report(),report())[0],2)

    def test_static_lines_are_not_a_moving_thumb(self):
        shot = {'file':'a.png','layout':{'scrollLeft':0,'clientWidth':280,'scrollWidth':400},
                'thumbSegments':[{'x':10,'end':206,'y':150},{'x':38,'end':234,'y':150}]}
        other = copy.deepcopy(shot)
        other['file'] = 'b.png'
        other['layout']['scrollLeft'] = 40
        self.assertIsNone(moving_thumb([shot,other]))
        shot['thumbSegments'] = shot['thumbSegments'][:1]
        other['thumbSegments'] = [{'x':38,'end':234,'y':150}]
        self.assertIsNotNone(moving_thumb([shot,other]))
        other['thumbSegments'][0]['y'] = 155
        self.assertIsNone(moving_thumb([shot,other]))

    def test_pixel_scan_includes_overlap_and_panel_edges(self):
        from PIL import Image, ImageDraw
        with tempfile.TemporaryDirectory() as temp:
            shots = []
            for i, (x, scroll) in enumerate([(23,0),(94,94)]):
                path = Path(temp)/f'{i}.png'
                im = Image.new('RGB',(320,120),(18,18,18))
                ImageDraw.Draw(im).rectangle((x,46,x+210,51),fill=(130,130,130))
                im.save(path)
                layout = {'filter':{'x':20,'y':20,'right':307,'bottom':54},
                          'search':{'y':58},'buttons':[{'bottom':52}],
                          'clientWidth':287,'scrollWidth':381,'scrollLeft':scroll}
                shots.append({'file':path.name,'layout':layout,
                              'thumbSegments':thumb_evidence(path,layout,{'width':320,'height':120})})
            match = moving_thumb(shots)
            self.assertIsNotNone(match)
            self.assertLess(match['thumbY'],match['labelsBottom'])


if __name__ == '__main__':
    unittest.main()
