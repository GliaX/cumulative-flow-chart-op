import requests
import schedule
import time
import yaml
import matplotlib.pyplot as plt
import datetime

class CumulativeFlowDiagram():
    def __init__(self) -> None:
       schedule.every(3).seconds.do(self.chart_data_task) ## todo every hour
       stream = open('token.yml', 'r')
       token_file = yaml.safe_load(stream)
       self.token = token_file['token']
       self.data = []
       self.headers = {
            'Authorization': 'Bearer ' + self.token
        }

       while True:
           schedule.run_pending()
           time.sleep(1)

    def chart_data_task(self):
        data = self.acquire_data()
        self.save_data(data)

    def get_statuses(self):
        response = requests.get('https://project.glia.org/api/v3/statuses', headers=self.headers)
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

        response = requests.get('https://project.glia.org/api/v3/workspaces/tourniquet/work_packages', params=params, headers=self.headers)
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

        x = list(timestamp for timestamp, _ in self.data)

        data_points = list(list(datum.values()) for _, datum in self.data)
        y = data_points
        y = list(map(list, zip(*y))) #rotate the Y axis list

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
        plt.savefig('chart.png')


CumulativeFlowDiagram()
