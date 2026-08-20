import requests
import schedule
import time
import yaml
import json
import os
import matplotlib.pyplot as plt
import datetime

class CumulativeFlowDiagram():
    DATA_FILE = 'data.json'
    CHART_FILE = 'chart.png'
    API_BASE = 'https://project.glia.org'
    PROJECT = 'miscellaneous-slash-small-parts'
    CHART_IMG = '<img class="op-uc-image op-uc-image_inline" src="/api/v3/attachments/{attachment_id}/content">'

    def __init__(self) -> None:
       schedule.every(3).seconds.do(self.chart_data_task) ## todo every hour
       stream = open('token.yml', 'r')
       token_file = yaml.safe_load(stream)
       self.token = token_file['token']
       self.data = []
       self.attachment_id = None
       self.load_data()
       self.headers = {
            'Authorization': 'Bearer ' + self.token
        }
       try:
           while True:
               schedule.run_pending()
               time.sleep(1)
       finally:
           plt.close('all')

    def chart_data_task(self):
        data = self.acquire_data()
        self.save_data(data)
        self.upload_chart()

    def load_data(self):
        if not os.path.exists(self.DATA_FILE):
            return
        try:
            with open(self.DATA_FILE, 'r', encoding='utf-8') as stream:
                raw = json.load(stream)
                if isinstance(raw, list):
                    raw = {'entries': raw}
                self.data = [
                    (datetime.datetime.fromisoformat(entry['timestamp']), entry['data'])
                    for entry in raw['entries']
                ]
                self.attachment_id = raw.get('attachmentId')
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            print(f'Warning: could not read history from {self.DATA_FILE}, starting with an empty chart')
            self.data = []

    def persist_data(self):
        entries = [
            {'timestamp': timestamp.isoformat(), 'data': data}
            for timestamp, data in self.data
        ]
        state = {'entries': entries, 'attachmentId': self.attachment_id}
        tmp_file = self.DATA_FILE + '.tmp'
        with open(tmp_file, 'w', encoding='utf-8') as stream:
            json.dump(state, stream, indent=2)
        os.replace(tmp_file, self.DATA_FILE)

    def get_statuses(self):
        response = requests.get(f'{self.API_BASE}/api/v3/statuses', headers=self.headers)
        response_json = response.json()
        statuses_collection = response_json['_embedded']['elements']
        statuses = list([status['name'] for status in statuses_collection])
        return statuses

    def acquire_data(self):
        params = {
            'offset': '1',
            'pageSize': '0',
            'filters': '[{ "status_id": { "operator": "o", "values": null }}]',
            'sortBy': '[["id", "asc"]]',
            'groupBy': 'status',
            'showSums': 'false',
        }

        response = requests.get(f'{self.API_BASE}/api/v3/workspaces/{self.PROJECT}/work_packages', params=params, headers=self.headers)
        response_json = response.json()
        keys = ['value', 'count']
        groups = response_json["groups"]

        data = list(map(lambda group: { key: group[key] for key in keys }, groups))
        data = list(map(lambda group: { group['value']: group['count']}, data))
        data_returned = {}
        data.reverse()
        for datum in data:
            data_returned.update(datum)
        return data_returned # "New" needs to be on top with "Closed" on the bottom

    def save_data(self, data):
        statuses = self.get_statuses()
        statuses.reverse()
        empty_chart = dict.fromkeys(statuses, 0) # "New" needs to be on top with "Closed" on the bottom
        data = empty_chart | data
        timestamped_data = datetime.datetime.now(datetime.UTC), data

        self.data.append(timestamped_data)
        self.persist_data()

        x = list(timestamp for timestamp, _ in self.data)

        y = [
            [datum.get(status, 0) for _, datum in self.data]
            for status in statuses
        ]

        self.render(statuses, x, y)

    def render(self, statuses, x, y):
        color_num = len(statuses)
        cm = plt.get_cmap('gist_rainbow')
        fig, ax = plt.subplots(figsize=(10, 10))
        ax.set_prop_cycle(color=[cm(1. * i / color_num) for i in range(color_num)])
        ax.stackplot(
            x, y,
            baseline='zero',
            labels=statuses
        )
        plt.legend()
        plt.savefig(self.CHART_FILE)

    def get_project(self):
        response = requests.get(f'{self.API_BASE}/api/v3/projects/{self.PROJECT}', headers=self.headers)
        response.raise_for_status()
        return response.json()

    def update_project_description(self, attachment_id):
        project = self.get_project()
        raw = project['description']['raw']
        if self.attachment_id is not None:
            raw = raw.replace(self.CHART_IMG.format(attachment_id=self.attachment_id), '')
        new_raw = f'{raw.rstrip()}\n\n{self.CHART_IMG.format(attachment_id=attachment_id)}'
        response = requests.patch(
            f'{self.API_BASE}/api/v3/projects/{self.PROJECT}',
            headers={**self.headers, 'Content-Type': 'application/json'},
            json={'description': {'format': 'markdown', 'raw': new_raw}},
        )
        response.raise_for_status()

    def upload_chart(self):
        with open(self.CHART_FILE, 'rb') as stream:
            response = requests.post(
                f'{self.API_BASE}/api/v3/attachments',
                headers=self.headers,
                files={
                    'metadata': (None, json.dumps({'fileName': self.CHART_FILE}), 'application/json'),
                    'file': (self.CHART_FILE, stream, 'image/png'),
                },
            )
        response.raise_for_status()
        attachment_id = response.json()['id']

        self.update_project_description(attachment_id)
        self.delete_stale_attachment()

        self.attachment_id = attachment_id
        self.persist_data()
        return attachment_id

    def delete_stale_attachment(self):
        if self.attachment_id is None:
            return
        try:
            response = requests.delete(f'{self.API_BASE}/api/v3/attachments/{self.attachment_id}', headers=self.headers)
            response.raise_for_status()
        except requests.RequestException:
            print(f'Warning: could not delete superseded attachment {self.attachment_id}')
        finally:
            self.attachment_id = None


if __name__ == '__main__':
    CumulativeFlowDiagram()
