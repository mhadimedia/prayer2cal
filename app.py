from flask import Flask, request, send_file
from timezonefinder import TimezoneFinder
from icalendar import Calendar, Event
from datetime import datetime, timedelta
from io import BytesIO
import pytz
import geocoder
import math
import re
import calendar

class PrayTimes():
    timeNames = {'fajr': 'Fajr', 'dhuhr': 'Dhuhr', 'asr': 'Asr', 'maghrib': 'Maghrib', 'isha': 'Isha'}
    methods = {'Jafari': {'name': 'Shia Ithna-Ashari, Leva Institute, Qum', 'params': {'fajr': 16, 'isha': 14, 'maghrib': 4, 'midnight': 'Jafari'}}}
    defaultParams = {'maghrib': '0 min', 'midnight': 'Standard'}
    calcMethod = 'Jafari'
    settings = {"imsak": '10 min', "dhuhr": '0 min', "asr": 'Standard', "highLats": 'NightMiddle'}
    timeFormat = '24h'
    timeSuffixes = ['am', 'pm']
    invalidTime = '-----'
    numIterations = 1
    offset = {}

    def __init__(self):
        for method, config in self.methods.items():
            for name, value in self.defaultParams.items():
                if not name in config['params'] or config['params'][name] is None:
                    config['params'][name] = value
        params = self.methods[self.calcMethod]['params']
        for name, value in params.items():
            self.settings[name] = value
        for name in self.timeNames:
            self.offset[name] = 0

    def getTimes(self, date, coords, timezone_str, dst=0, format=None):
        self.lat = coords[0]
        self.lng = coords[1]
        self.elv = coords[2] if len(coords) > 2 else 0
        if format != None:
            self.timeFormat = format
        if type(date).__name__ == 'date':
            date = (date.year, date.month, date.day)
        current_time = datetime.now(pytz.timezone(timezone_str))
        self.timeZone = current_time.utcoffset().total_seconds() / 3600.0
        self.jDate = self.julian(date[0], date[1], date[2]) - self.lng / (15 * 24.0)
        return self.computeTimes()

    def getFormattedTime(self, time, format, suffixes=None):
        if math.isnan(time):
            return self.invalidTime
        if format == 'Float':
            return time
        if suffixes == None:
            suffixes = self.timeSuffixes
        time = self.fixhour(time + 0.5 / 60)
        hours = math.floor(time)
        minutes = math.floor((time - hours) * 60)
        suffix = suffixes[0 if hours < 12 else 1] if format == '12h' else ''
        formattedTime = "%02d:%02d" % (hours, minutes) if format == "24h" else "%d:%02d" % ((hours + 11) % 12 + 1, minutes)
        return formattedTime + suffix

    def midDay(self, time):
        eqt = self.sunPosition(self.jDate + time)[1]
        return self.fixhour(12 - eqt)

    def sunAngleTime(self, angle, time, direction=None):
        try:
            decl = self.sunPosition(self.jDate + time)[0]
            noon = self.midDay(time)
            t = 1 / 15.0 * self.arccos((-self.sin(angle) - self.sin(decl) * self.sin(self.lat)) /
                                       (self.cos(decl) * self.cos(self.lat)))
            return noon + (-t if direction == 'ccw' else t)
        except ValueError:
            return float('nan')

    def asrTime(self, factor, time):
        decl = self.sunPosition(self.jDate + time)[0]
        angle = -self.arccot(factor + self.tan(abs(self.lat - decl)))
        return self.sunAngleTime(angle, time)

    def sunPosition(self, jd):
        D = jd - 2451545.0
        g = self.fixangle(357.529 + 0.98560028 * D)
        q = self.fixangle(280.459 + 0.98564736 * D)
        L = self.fixangle(q + 1.915 * self.sin(g) + 0.020 * self.sin(2 * g))
        R = 1.00014 - 0.01671 * self.cos(g) - 0.00014 * self.cos(2 * g)
        e = 23.439 - 0.00000036 * D
        RA = self.arctan2(self.cos(e) * self.sin(L), self.cos(L)) / 15.0
        eqt = q / 15.0 - self.fixhour(RA)
        decl = self.arcsin(self.sin(e) * self.sin(L))
        return (decl, eqt)

    def julian(self, year, month, day):
        if month <= 2:
            year -= 1
            month += 12
        A = math.floor(year / 100)
        B = 2 - A + math.floor(A / 4)
        return math.floor(365.25 * (year + 4716)) + math.floor(30.6001 * (month + 1)) + day + B - 1524.5

    def computePrayerTimes(self, times):
        times = self.dayPortion(times)
        params = self.settings
        fajr = self.sunAngleTime(self.eval(params['fajr']), times['fajr'], 'ccw')
        dhuhr = self.midDay(times['dhuhr'])
        asr = self.asrTime(self.asrFactor(params['asr']), times['asr'])
        maghrib = self.sunAngleTime(self.eval(params['maghrib']), times['maghrib'])
        sunset = self.sunAngleTime(0, times['maghrib'])  # Adding Sunset
        sunrise = self.sunAngleTime(0, times['fajr'], 'ccw')  # Adding Sunrise
        midnight = self.midDay(times['dhuhr'] + 12)  # Adding Midnight
        return {'fajr': fajr, 'dhuhr': dhuhr, 'asr': asr, 'maghrib': maghrib, 'sunset': sunset, 'sunrise': sunrise, 'midnight': midnight}  # Added new times

    def computeTimes(self):
        times = {'fajr': 5, 'dhuhr': 12, 'asr': 13, 'maghrib': 18, 'isha': 18, 'sunset': 18, 'sunrise': 5, 'midnight': 12}  # Added new times
        for i in range(self.numIterations):
            times = self.computePrayerTimes(times)
        times = self.adjustTimes(times)
        for name, value in times.items():
            times[name] = self.getFormattedTime(value, self.timeFormat)
        return times

    def adjustTimes(self, times):
        params = self.settings
        for name, value in times.items():
            times[name] += self.timeZone - self.lng / 15
        times['dhuhr'] += self.minToTime(self.eval(params['dhuhr']))
        return times

    def adjustHighLats(self, times):
        params = self.settings
        nightTime = self.timeDiff(times['sunset'], times['sunrise'])
        times['fajr'] = self.adjustHLTime(times['fajr'], times['sunrise'], self.eval(params['fajr']), nightTime, 'ccw')
        times['isha'] = self.adjustHLTime(times['isha'], times['sunset'], self.eval(params['isha']), nightTime)
        return times

    def adjustHLTime(self, time, base, angle, night, direction=None):
        portion = self.nightPortion(angle, night)
        diff = self.timeDiff(time, base) if direction == 'ccw' else self.timeDiff(base, time)
        if math.isnan(time) or diff > portion:
            time = base + (-portion if direction == 'ccw' else portion)
        return time

    def nightPortion(self, angle, night):
        method = self.settings['highLats']
        portion = 1 / 2.0  # Midnight
        if method == 'AngleBased':
            portion = 1 / 60.0 * angle
        return portion * night

    def dayPortion(self, times):
        for name, value in times.items():
            times[name] /= 24.0
        return times

    def asrFactor(self, asrParam):
        methods = {'Standard': 1, 'Hanafi': 2}
        return methods[asrParam] if asrParam in methods else self.eval(asrParam)

    def minToTime(self, time):
        return time / 60.0

    def eval(self, expr):
        if 'min' in str(expr):
            return float(expr.split()[0]) / 60.0
        return float(re.sub(r'(\d+)(?:[a-zA-Z])', r'\1', str(expr)))

    def timeDiff(self, time1, time2):
        return self.fixhour(time2 - time1)

    def fixhour(self, hour):
        hour = hour - 24.0 * math.floor(hour / 24.0)
        hour = hour < 0 and hour + 24.0 or hour
        return hour

    def fixangle(self, angle):
        angle = angle - 360.0 * math.floor(angle / 360.0)
        angle = angle < 0 and angle + 360.0 or angle
        return angle

    def radToDeg(self, angleRad):
        return (180.0 * angleRad) / math.pi

    def degToRad(self, angleDeg):
        return (math.pi * angleDeg) / 180.0

    def sin(self, d):
        return math.sin(self.degToRad(d))

    def cos(self, d):
        return math.cos(self.degToRad(d))

    def tan(self, d):
        return math.tan(self.degToRad(d))

    def arcsin(self, x):
        return self.radToDeg(math.asin(x))

    def arccos(self, x):
        return self.radToDeg(math.acos(x))

    def arctan(self, x):
        return self.radToDeg(math.atan(x))

    def arccot(self, x):
        return self.radToDeg(math.atan(1 / x))

    def arctan2(self, y, x):
        return self.radToDeg(math.atan2(y, x))

    def create_ical(self, year, coords, timezone, extra=None, filename='prayer_times.ics', days=1):
        cal = Calendar()
        cal.add('prodid', '-//Your App//example.com//')
        cal.add('version', '2.0')

        tz = pytz.timezone(timezone)  # Use the provided timezone
        current_time = datetime.now(tz)
        is_dst = current_time.dst() != timedelta(0)

        for day_offset in range(days):  # Loop through the number of days
            current_date = datetime.today() + timedelta(days=day_offset)
            date_tuple = (current_date.year, current_date.month, current_date.day)
            times = self.getTimes(date_tuple, coords, timezone, is_dst)

            for prayer_name in ['Fajr', 'Dhuhr & Asr', 'Maghrib & Isha']:
                event = Event()
                event.add('summary', prayer_name)

                if prayer_name == 'Dhuhr & Asr':
                    prayer_time = times['dhuhr']
                elif prayer_name == 'Maghrib & Isha':
                    prayer_time = times['maghrib']
                else:
                    prayer_time = times[prayer_name.lower()]

                prayer_datetime = datetime(current_date.year, current_date.month, current_date.day,
                                        int(prayer_time.split(':')[0]), int(prayer_time.split(':')[1]))
                event.add('dtstart', prayer_datetime)
                event.add('duration', timedelta(minutes=30))
                cal.add_component(event)

            # Conditionally add extra times
            if extra:
                print("Extra times received:", extra)  # Debugging line
                print("Times dictionary:", times)  # Debugging line
                for extra_time in extra:
                    if extra_time.lower() in times:
                        print("Adding extra time:", extra_time)  # Debugging line
                        event = Event()
                        event.add('summary', extra_time)
                        extra_time_value = times[extra_time.lower()]
                        extra_datetime = datetime(current_date.year, current_date.month, current_date.day,
                                                int(extra_time_value.split(':')[0]), int(extra_time_value.split(':')[1]))
                        event.add('dtstart', extra_datetime)
                        event.add('duration', timedelta(minutes=30))
                        cal.add_component(event)


        # Save to a BytesIO object to avoid file system dependency
        import io
        file_object = io.BytesIO()
        file_object.write(cal.to_ical())
        file_object.seek(0)

        return file_object  # Return the BytesIO object


app = Flask(__name__)

@app.route('/')
def index():
    return open("index.html").read()

@app.route('/generate_ical', methods=['POST'])
def generate_ical():
    method = request.form['method']
    days = int(request.form['days'])
    extra = request.form.getlist('extra')
    lat = float(request.form['lat'])
    lng = float(request.form['lng'])

    tf = TimezoneFinder()
    timezone_str = tf.timezone_at(lat=lat, lng=lng)

    year = datetime.today().year
    coords = (lat, lng)
    prayTimes = PrayTimes()
    filename = f"{timezone_str.replace('/', '_')}_prayer_times.ics"

    print(f"Extra times selected: {extra}")
    file_object = prayTimes.create_ical(year, coords, timezone_str, extra=extra, filename=filename, days=days)

    return send_file(file_object, as_attachment=True, download_name=filename, mimetype='text/calendar')

if __name__ == '__main__':
    app.run(debug=True)