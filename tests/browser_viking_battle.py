from pathlib import Path
from playwright.sync_api import sync_playwright, expect
root=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
 browser=p.chromium.launch()
 for width in (1440,390):
  page=browser.new_page(viewport={'width':width,'height':950})
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.clock.install()
  page.set_content('<html data-theme="viking"><body style="margin:0;background:#20383b"><div class="ambient-scene"></div></body></html>')
  page.add_style_tag(content=(root/'static/viking.css').read_text(encoding='utf-8-sig'))
  page.add_script_tag(content=(root/'static/viking-battle-model.js').read_text(encoding='utf-8-sig'))
  page.evaluate('''() => { let seed=71;const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};const Model=window.FjordBattleModel;window.FjordBattleModel=class extends Model {constructor(count){super(count,random);window.testBattle=this;}};}''')
  page.add_script_tag(content=(root/'static/viking-battle.js').read_text(encoding='utf-8-sig'))
  def advance(seconds):
   page.evaluate('seconds=>{for(let i=0;i<seconds*20;i++)testBattle.advance(.05,innerWidth,innerHeight);dispatchEvent(new Event("resize"));}',seconds)
  advance(5)
  expect(page.locator('.viking-longship:not([hidden])')).to_have_count(2)
  assert page.evaluate('testBattle.units.some(u=>u.state==="sailing")')
  page.screenshot(path=str(root/f'test-results/viking-boats-{width}.png'))
  advance(27)
  assert page.evaluate('testBattle.units.some(u=>u.state==="fighting")')
  alive=page.locator('.viking-warrior:not([disabled])').last
  alive.evaluate('e=>e.click()')
  advance(.2)
  expect(page.locator('.viking-blood i').first).to_be_visible()
  page.screenshot(path=str(root/f'test-results/viking-combat-{width}.png'))
  advance(2)
  assert page.locator('.viking-blood').count()<=40
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  assert not errors,errors
  page.close()
 browser.close()
print('PASS boats, visible combat and blood, desktop/mobile, bounded DOM and console')
