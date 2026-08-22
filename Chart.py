import requests
import schedule
import time
import yaml
import json
import os
import matplotlib.pyplot as plt
import datetime

class CumulativeFlowDiagram():
    DATA_FILE = 'data-{}.json'
    CHART_FILE = 'chart.png'
    API_BASE = 'https://project.glia.org'
    PROJECTS = ['miscellaneous-slash-small-parts']
    CHART_IMG = '<img class="op-uc-image op-uc-image_inline" src="/api/v3/attachments/{attachment_id}/content">'

    def __init__(self, project) -> None:
       self.project = project
       schedule.every(3).seconds.do(self.chart_data_task) ## todo every hour
       stream = open('token.yml', 'r')
       token_file = yaml.safe_load(stream)
       self.token = token_file['token']
       self.data = []
       self.attachment_id = None
       self.grid_id = None
       self.widget_id = None
       self.load_data()
       self.headers = {
            'Authorization': 'Bearer ' + self.token
        }

    def chart_data_task(self):
        data = self.acquire_data()
        if self.data and all(self.data[-1][1].get(status, 0) == count for status, count in data.items()):
            return
        self.save_data(data)
        self.upload_chart()

    def load_data(self):
        data_file = self.DATA_FILE.format(self.project)
        if not os.path.exists(data_file):
            return
        try:
            with open(data_file, 'r', encoding='utf-8') as stream:
                raw = json.load(stream)
                if isinstance(raw, list):
                    raw = {'entries': raw}
                self.data = [
                    (datetime.datetime.fromisoformat(entry['timestamp']), entry['data'])
                    for entry in raw['entries']
                ]
                self.attachment_id = raw.get('attachmentId')
                self.grid_id = raw.get('gridId')
                self.widget_id = raw.get('widgetId')
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            print(f'Warning: could not read history from {data_file}, starting with an empty chart')
            self.data = []
            self.attachment_id = None
            self.grid_id = None
            self.widget_id = None

    def persist_data(self):
        entries = [
            {'timestamp': timestamp.isoformat(), 'data': data}
            for timestamp, data in self.data
        ]
        state = {'entries': entries, 'attachmentId': self.attachment_id, 'gridId': self.grid_id, 'widgetId': self.widget_id}
        data_file = self.DATA_FILE.format(self.project)
        tmp_file = data_file + '.tmp'
        with open(tmp_file, 'w', encoding='utf-8') as stream:
            json.dump(state, stream, indent=2)
        os.replace(tmp_file, data_file)

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

        response = requests.get(f'{self.API_BASE}/api/v3/workspaces/{self.project}/work_packages', params=params, headers=self.headers)
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
        response = requests.get(f'{self.API_BASE}/api/v3/projects/{self.project}', headers=self.headers)
        response.raise_for_status()
        return response.json()

    def update_project_description(self, attachment_id):
        project = self.get_project()
        raw = project['description']['raw']
        if self.attachment_id is not None:
            raw = raw.replace(self.CHART_IMG.format(attachment_id=self.attachment_id), '')
        new_raw = f'{raw.rstrip()}\n\n{self.CHART_IMG.format(attachment_id=attachment_id)}'
        response = requests.patch(
            f'{self.API_BASE}/api/v3/projects/{self.project}',
            headers={**self.headers, 'Content-Type': 'application/json'},
            json={'description': {'format': 'markdown', 'raw': new_raw}},
        )
        response.raise_for_status()

    def upload_chart(self):
        grid, widget = self.find_or_create_chart_widget()
        with open(self.CHART_FILE, 'rb') as stream:
            response = requests.post(
                f'{self.API_BASE}/api/v3/grids/{self.grid_id}/attachments',
                headers=self.headers,
                files={
                    'metadata': (None, json.dumps({'fileName': self.CHART_FILE, 'contentType': 'image/png'}), 'application/json'),
                    'file': (self.CHART_FILE, stream, 'image/png'),
                },
            )
        response.raise_for_status()
        attachment_id = response.json()['id']

        self.update_project_description(attachment_id)
        widget['options']['text'] = {'format': 'markdown', 'raw': self.CHART_IMG.format(attachment_id=attachment_id)}
        response = requests.patch(
            f'{self.API_BASE}/api/v3/grids/{self.grid_id}',
            headers={**self.headers, 'Content-Type': 'application/json'},
            json={'widgets': grid['widgets']},
        )
        response.raise_for_status()
        self.delete_stale_attachment()

        self.attachment_id = attachment_id
        self.persist_data()
        return attachment_id

    def find_or_create_chart_widget(self):
        grid = self.find_grid()
        if grid is None:
            raise RuntimeError(f'no overview grid found for {self.project}')
        widget = self.find_widget(grid)
        if widget is None:
            widget = self.create_chart_widget(grid)
        self.grid_id = grid['id']
        self.widget_id = widget['id']
        return grid, widget

    def find_grid(self):
        if self.grid_id is not None:
            response = requests.get(f'{self.API_BASE}/api/v3/grids/{self.grid_id}', headers=self.headers)
            if response.ok and response.json()['_links']['scope']['href'] == f'/projects/{self.project}':
                return response.json()
        response = requests.get(f'{self.API_BASE}/api/v3/grids', headers=self.headers, params={'pageSize': '100'})
        response.raise_for_status()
        for candidate in response.json()['_embedded']['elements']:
            if candidate['_links']['scope']['href'] == f'/projects/{self.project}':
                return candidate
        return None

    def find_widget(self, grid):
        widgets = grid['widgets']
        widget = next((w for w in widgets if w['id'] == self.widget_id), None)
        if widget is None:
            widget = next((w for w in widgets if w['identifier'] == 'custom_text' and w['options'].get('name') == 'Cumulative flow diagram'), None)
        return widget

    def create_chart_widget(self, grid):
        widget = {
            'identifier': 'custom_text',
            'startRow': grid['rowCount'],
            'endRow': grid['rowCount'] + 1,
            'startColumn': 1,
            'endColumn': 2,
            'options': {'name': 'Cumulative flow diagram', 'text': {'format': 'markdown', 'raw': ''}},
        }
        grid['widgets'].append(widget)
        response = requests.patch(
            f'{self.API_BASE}/api/v3/grids/{grid["id"]}',
            headers={**self.headers, 'Content-Type': 'application/json'},
            json={'rowCount': grid['rowCount'] + 1, 'widgets': grid['widgets']},
        )
        response.raise_for_status()
        updated = response.json()
        return next(w for w in updated['widgets'] if w['identifier'] == 'custom_text' and w['options'].get('name') == 'Cumulative flow diagram')

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
    diagrams = [CumulativeFlowDiagram(project) for project in CumulativeFlowDiagram.PROJECTS]
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    finally:
        plt.close('all')
