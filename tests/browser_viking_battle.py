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
  advance(12)
  assert 5<=page.locator('.viking-longship:not([hidden])').count()<=8
  assert page.evaluate('testBattle.units.some(u=>u.state==="sailing")')
  page.screenshot(path=str(root/f'test-results/viking-boats-{width}.png'))
  advance(page.evaluate('testBattle.boats[1].landAt+.6-testBattle.time'))
  assert page.evaluate('testBattle.units.some(u=>u.state==="landing")')
  page.screenshot(path=str(root/f'test-results/viking-landing-{width}.png'))
  advance(page.evaluate('testBattle.arrivalEnd+6-testBattle.time'))
  expect(page.locator('.viking-warrior.is-archer').first).to_be_visible()
  for _ in range(200):
   if page.locator('.viking-arrow').count() and page.evaluate('testBattle.units.some(u=>u.state==="fighting")'):break
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
  page.evaluate('''()=>{const u=testBattle.units.find(u=>u.deadAt===null&&!u.lostLeg&&!u.lostArm);u.hp=5;u.x=.5;u.y=.85;const random=testBattle.random;testBattle.random=()=>.1;testBattle.wound(u,1,true);testBattle.wound(u,1,true);testBattle.random=random;}''')
  advance(1)
  expect(page.locator('.is-crawling').first).to_be_visible()
  expect(page.locator('.viking-blood-trail').first).to_be_visible()
  expect(page.locator('.viking-catapult').first).to_be_visible()
  page.screenshot(path=str(root/f'test-results/viking-crawling-{width}.png'))
  victim_id=page.evaluate('''()=>{const u=testBattle.units.find(u=>u.deadAt===null&&!u.withdrawing);u.hp=1;const random=testBattle.random;testBattle.random=()=>0;testBattle.wound(u,1,true);testBattle.random=random;dispatchEvent(new Event('resize'));return u.id;}''')
  expect(page.locator('.viking-warrior').nth(victim_id).locator('.viking-head')).to_be_hidden()
  expect(page.locator('.viking-limb.head svg').first).to_be_visible()
  advance(.2)
  page.screenshot(path=str(root/f'test-results/viking-head-hit-{width}.png'))
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  round_before=page.evaluate('testBattle.round')
  page.evaluate('()=>{for(const u of testBattle.units)if(u.team===1)testBattle.kill(u.id);dispatchEvent(new Event("resize"));}')
  expect(page.locator('.has-victory-flag .viking-victory-flag')).to_be_visible()
  page.screenshot(path=str(root/f'test-results/viking-victory-{width}.png'))
  advance(13.2)
  assert page.evaluate('testBattle.round')==round_before+1
  assert page.locator('.has-victory-flag').count()==0
  expect(page.locator('.viking-settlement-house')).to_have_count(4)
  expect(page.locator('.viking-settlement-house.is-church')).to_have_count(1)
  assert page.locator('.settlement-defender').count()==(20 if width<700 else 32)
  advance(page.evaluate('testBattle.arrivalEnd+1-testBattle.time'))
  page.evaluate('()=>{for(const u of testBattle.units)if(u.team===0)testBattle.kill(u.id);dispatchEvent(new Event("resize"));}')
  assert page.evaluate('testBattle.phase')=='raid'
  advance(7)
  for _ in range(70):
   if page.evaluate('testBattle.units.some(u=>u.state==="inside")'):break
   advance(.1)
  assert page.evaluate('testBattle.units.some(u=>u.state==="inside")')
  assert page.evaluate('testBattle.units.filter(u=>u.state==="inside").every(u=>u.team===1)')
  page.screenshot(path=str(root/f'test-results/viking-settlement-raid-{width}.png'))
  advance(page.evaluate('testBattle.exitStart-testBattle.time-.1'))
  expect(page.locator('.has-loot .viking-loot').first).to_be_visible()
  assert page.locator('.settlement-defender.has-loot').count()==0
  page.screenshot(path=str(root/f'test-results/viking-settlement-loot-{width}.png'))
  assert not errors,errors
  page.keyboard.press('Escape')
  expect(page.locator('#battle-full-view')).to_be_visible()
  assert not page.locator('main').evaluate('e=>e.inert')
  expect(page.locator('#battle-full-view')).to_be_focused()
  page.close()
 browser.close()
print('PASS boats, visible combat and blood, desktop/mobile, bounded DOM and console')
