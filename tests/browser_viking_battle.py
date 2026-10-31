from pathlib import Path
import base64
from playwright.sync_api import sync_playwright, expect
root=Path(__file__).resolve().parents[1]
with sync_playwright() as p:
 browser=p.chromium.launch()
 for width in (1440,390):
  page=browser.new_page(viewport={'width':width,'height':950})
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.clock.install()
  page.set_content('<html data-theme="viking"><body style="margin:0;background:#20383b"><div class="ambient-scene"></div><main><button id="battle-full-view">Fuld visning</button></main></body></html>')
  page.add_style_tag(content=(root/'static/ambient.css').read_text(encoding='utf-8-sig'))
  backdrop='data:image/svg+xml;base64,'+base64.b64encode((root/'static/viking-fjord.svg').read_bytes()).decode()
  page.add_style_tag(content=(root/'static/viking.css').read_text(encoding='utf-8-sig').replace('/static/viking-fjord.svg',backdrop))
  page.add_script_tag(content=(root/'static/viking-battle-model.js').read_text(encoding='utf-8-sig'))
  page.evaluate('''() => { let seed=71;const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/4294967296;};const Model=window.FjordBattleModel;window.FjordBattleModel=class extends Model {constructor(count){super(count,random);window.testBattle=this;}};}''')
  page.add_script_tag(content=(root/'static/viking-battle.js').read_text(encoding='utf-8-sig'))
  page.locator('#battle-full-view').click()
  expect(page.locator('body')).to_have_class('viking-full-view')
  assert page.locator('main').evaluate('e=>e.inert')
  def advance(seconds):
   page.evaluate('seconds=>{for(let i=0;i<seconds*20;i++)testBattle.advance(.05,innerWidth,innerHeight);dispatchEvent(new Event("resize"));}',seconds)
  advance(5)
  assert 5<=page.locator('.viking-longship:not([hidden])').count()<=8
  assert page.evaluate('testBattle.units.some(u=>u.state==="sailing")')
  page.screenshot(path=str(root/f'test-results/viking-boats-{width}.png'))
  advance(3.5)
  assert page.evaluate('testBattle.units.some(u=>u.state==="landing")')
  page.screenshot(path=str(root/f'test-results/viking-landing-{width}.png'))
  advance(23.5)
  expect(page.locator('.viking-warrior.is-archer').first).to_be_visible()
  for _ in range(30):
   if page.locator('.viking-arrow').count():break
   advance(.1)
  expect(page.locator('.viking-arrow').first).to_be_visible()
  assert page.evaluate('testBattle.units.some(u=>u.state==="fighting")')
  alive=page.locator('.viking-warrior:not([disabled])').last
  alive.evaluate('e=>e.click()')
  advance(.2)
  expect(page.locator('.viking-blood i').first).to_be_visible()
  page.screenshot(path=str(root/f'test-results/viking-combat-{width}.png'))
  advance(2)
  assert page.locator('.viking-blood').count()<=40
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  round_before=page.evaluate('testBattle.round')
  page.evaluate('()=>{for(const u of testBattle.units)if(u.team===1)testBattle.kill(u.id);dispatchEvent(new Event("resize"));}')
  expect(page.locator('.has-victory-flag .viking-victory-flag')).to_be_visible()
  page.screenshot(path=str(root/f'test-results/viking-victory-{width}.png'))
  advance(13.2)
  assert page.evaluate('testBattle.round')==round_before+1
  assert page.locator('.has-victory-flag').count()==0
  assert not errors,errors
  page.keyboard.press('Escape')
  expect(page.locator('#battle-full-view')).to_be_visible()
  assert not page.locator('main').evaluate('e=>e.inert')
  expect(page.locator('#battle-full-view')).to_be_focused()
  page.close()
 browser.close()
print('PASS boats, visible combat and blood, desktop/mobile, bounded DOM and console')
