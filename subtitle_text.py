"""Subtitle text contracts. The model never receives or generates timestamps."""
import re

LANGUAGES = {'da':'Dansk','en':'Engelsk','sv':'Svensk','no':'Norsk','de':'Tysk',
             'fr':'Fransk','es':'Spansk','it':'Italiensk','nl':'Nederlandsk',
             'pt':'Portugisisk','fi':'Finsk','pl':'Polsk','uk':'Ukrainsk',
             'ar':'Arabisk','ja':'Japansk','ko':'Koreansk','zh':'Kinesisk'}
ALIASES = dict(zip('dan eng swe nor deu fra spa ita nld por fin pol ukr ara jpn kor zho'.split(), LANGUAGES))
ALIASES.update(ger='de',fre='fr',dut='nl',chi='zh',nob='no',nno='no',nb='no',nn='no')
TIME = r'\d{2,}:\d{2}:\d{2},\d{3}'
TIMING = re.compile(r'^('+TIME+r') --> ('+TIME+r')(?P<settings>[^\r\n]*)$')


def language(value):
    value = str(value or 'und').lower().split('-')[0]
    return ALIASES.get(value, value)


def milliseconds(value):
    h, m, s, ms = map(int, re.split('[:,]', value))
    if m > 59 or s > 59: raise ValueError('Ugyldig tidskode.')
    return ((h*60+m)*60+s)*1000+ms


def timestamp(ms):
    h, rest = divmod(ms, 3600000); m, rest = divmod(rest, 60000); s, rest = divmod(rest, 1000)
    return f'{h:02}:{m:02}:{s:02},{rest:03}'


def parse_srt(text):
    if len(text) > 8*1024*1024: raise ValueError('Underteksten er for stor (maks. 8 MB).')
    cues = []
    for block in re.split(r'\n[ \t]*\n', text.lstrip('\ufeff').replace('\r\n','\n').strip()):
        lines = block.splitlines()
        if lines and lines[0].strip().isdigit(): lines.pop(0)
        match = TIMING.fullmatch(lines[0]) if lines else None
        if not match or len(lines) < 2 or milliseconds(match[2]) <= milliseconds(match[1]):
            raise ValueError('Underteksten indeholder en ugyldig SRT-blok.')
        body = '\n'.join(lines[1:]).strip()
        if not body or '-->' in body: raise ValueError('En undertekstblok er tom eller mangler blokadskillelse.')
        cues.append({'id':len(cues)+1,'timing':lines[0],'text':body})
    if not cues or len(cues)>20000: raise ValueError('Ugyldigt antal undertekstblokke.')
    return cues


def render_srt(cues):
    text = '\n\n'.join(f"{i}\n{c['timing']}\n{c['text']}" for i,c in enumerate(cues,1))+'\n'
    parse_srt(text)
    return text


def translated(cues, result):
    if not isinstance(result, dict) or not isinstance(result.get('cues'),list):
        raise ValueError('AI-svaret har et ugyldigt format. Prøv igen.')
    rows = result['cues']
    if len(rows)!=len(cues) or any(not isinstance(r,dict) for r in rows):
        raise ValueError('AI-svaret mangler undertekstblokke. Intet er gemt.')
    output = []
    for original,row in zip(cues,rows):
        body = row.get('text')
        if (type(row.get('id')) is not int or row['id']!=original['id'] or not isinstance(body,str)
                or not body.strip() or len(body)>20000 or '\x00' in body or '-->' in body):
            raise ValueError('AI-svaret ændrede underteksternes struktur. Intet er gemt.')
        body = re.sub(r'\n[ \t]*\n+', '\n', body.replace('\r\n','\n').replace('\r','\n')).strip()
        output.append({**original,'text':body})
    return output
