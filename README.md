## Useful commands
Deploy server and detach process
```bash
conda activate quicksin # Or whatever environment you use
nohup sh server.sh & tail -f nohup.out
```
kill server and uwsgi processes
```bash
ps x | grep [s]erver | sed 's/^ \+\([0-9]\+\).*/\1/g' | xargs kill && \
killall uwsgi && watch 'ps x'
```
Run the staging server that skips audio in favor of logged answers
```bash
FLASK_APP="debug:app" flask run -p 8088 --debug
```

To verify that the server is running, issue the following command from a terminal
```bash
curl -X POST https://quicksin.stanford.edu/jnd/api/lists
```

To run offline ASR on the collected utterances (From Kent's account):
```bash
source ~kent/env/bin/activate
python3 offline_asr.py --model tiny.en
```

To run offline ASR on the collected utterances (From Malcolm's account):
```bash
conda activate quicksin
python3 offline_asr.py --model tiny.en
```

[Colab that synthesizes the needed CSV transcript files](
https://colab.research.google.com/drive/1EOPHV74jawtxrZSQh94Dp5AFAGFt0Pkn?usp=sharing)

[Google drive folder with all the segmented data](
https://drive.google.com/drive/folders/1XfQn3eAjBY6h9Q7wruck7zqJVS7cCEQG)
And within that the Web_Audio folder has the renamed data we play to subjects.

## Adding tests
To add a new type of audio test do the following:
1. Add a section to the [colab](https://colab.research.google.com/drive/1EOPHV74jawtxrZSQh94Dp5AFAGFt0Pkn?usp=sharing) to create the transcript (csv) for the new test data.
1. Add new transcript to the `metadata` folder matching the path in the spec class below
2. In `projects.py`, add a new spec, blueprint and database classes for the project
3. In `api.py`,
    1. Add the database and blueprint class to the import at the top,
    2. Add the new database class to the `ExperimentDB` parents,
    3. Add the blueprint class name to the dictionary of `APIBlueprint.projects`
4. To install a new test
    1. Run `python migrate.py projects.[ProjectDBClass]` (subclass of AudioDB)
5. To update an existing database (online test) do the following:
    1. Run `python migrate.py  # No extra arguments`
    2. Run `python migrate.py projects.[ProjectDBClass] --rewrite`
6. Add the audio files to `static/audio/[project]/*.wav`
7. Add `static/[project].html`, replace the project name in the inline script tag (let audio =..), and add `static/[project]_done.html`

## OAuth
1) [login client](https://github.com/kentslaney/login/) (as a sibling to jnd):
```bash
git clone https://github.com/kentslaney/login.git
```

2) [Google OAuth credentials page](
https://console.cloud.google.com/apis/credentials) Web application replacing
`sub.domain.tld` with the real subdomain

Authorized JavaScript origins: `https://sub.domain.tld`

Authorized redirect URIs: `https://sub.domain.tld/login/google/authorized`

3) put the resulting credentials in `login/run/credentials.json`:
```json
{
    "google": {"id": "username", "secret": "API key"}
}
```

4) in `login`
```bash
sh server.sh start
```

5) update owner id in `protected.py`:
```
malcolmslaney@gmail.com 110909794990702804159
mslaney@stanford.edu    100987618575971262389
Varsha Mysore Athreya   114354889327043931514
Matthew Fitzgerald      101607400393342786056
```

6) update `protected.py`'s value for `login_required.prefix` to the real
subdomain

7) with the environment running the QuickSIN server:
```bash
pip install -e path/to/login # ../login probably
```

8) change `server.sh` from `uwsgi.ini` to `login.ini` and start the QuickSIN
server

9) go to `/login/access/view/invite`, check the audio group, remove the
`invitees` value if you want the invite to work for more than one person,
and change the redirect URL to `/jnd`, then you can distribute the invite
