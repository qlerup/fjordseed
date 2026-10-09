const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const helper = source.slice(source.indexOf('function torrentStatus('), source.indexOf('function card('));
const context = vm.createContext({});
vm.runInContext(helper, context);
assert.equal(context.torrentStatus({state:'stalledUP',progress:1,upspeed:0}), 'Seeder \u2013 venter p\u00e5 downloadere');
assert.equal(context.torrentStatus({state:'uploading'}), 'Seeder \u2013 uploader');
assert.equal(context.torrentStatus({state:'pausedUP'}), 'Seeding sat p\u00e5 pause');
assert.equal(context.torrentStatus({state:'stoppedUP'}), 'Seeding stoppet');
assert.equal(context.torrentStatus({state:'queuedUP'}), 'Afventer seeding');
assert.equal(context.torrentStatus({state:'downloading'}), 'Downloader');
assert.equal(context.torrentStatus({state:'missingFiles'}), 'Filer mangler');
assert.equal(context.torrentStatus({state:'futureState'}), 'Ukendt status');
console.log('PASS active, idle, paused, stopped, queued seeding and download states');

for(const target of [1,2,5]){
 const progress=context.seedingProgress({ratio:1,ratio_limit:target,seeding_time:0,seeding_time_limit:2940,state:'stalledUP'});
 assert.equal(progress.fraction,1/target);
 assert.equal(progress.active,true);
}
assert.equal(context.seedingProgress({ratio:0,ratio_limit:5,seeding_time:88200,seeding_time_limit:2940}).fraction,.5);
assert.equal(context.seedingProgress({ratio:0,ratio_limit:5,seeding_time:176400,seeding_time_limit:2940}).fraction,1);
assert.equal(context.seedingProgress({ratio:0,ratio_limit:5,seeding_time:172800,seeding_time_limit:2940}).fraction,48/49);
assert.equal(context.seedingProgress({ratio:7,ratio_limit:5}).fraction,1);
assert.equal(context.seedingProgress({ratio:1,ratio_limit:5,state:'stoppedUP'}).active,false);
assert.equal(context.seedingProgress({ratio:1,ratio_limit:5,seeding_time:176400,seeding_time_limit:-1}).fraction,.2);
console.log('PASS configured ratio 1/2/5, time alternative, cap and paused seeding');
