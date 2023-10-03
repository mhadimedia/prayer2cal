navigator.geolocation.getCurrentPosition(function (position) {
    const lat = position.coords.latitude;
    const lng = position.coords.longitude;
    const prayTimes = new PrayTimes();

    $("#prayer-form").submit(function (e) {
        e.preventDefault();

        const method = $("#method").val();
        const days = parseInt($("#days").val());
        const extra = [];

        $("input[name='extra']:checked").each(function () {
            extra.push($(this).val().toLowerCase());
        });

        const cal = ics();
        for (let dayOffset = 0; dayOffset < days; dayOffset++) {
            const date = new Date();
            date.setDate(date.getDate() + dayOffset);

            const times = prayTimes.getTimes(date, [lat, lng], null, null, method);

            for (const prayerName in times) {
                if (extra.includes(prayerName) || ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha'].includes(prayerName)) {
                    const timeParts = times[prayerName].split(":");
                    const prayerDate = new Date(date.getFullYear(), date.getMonth(), date.getDate(), timeParts[0], timeParts[1]);
                    cal.addEvent(prayerName.charAt(0).toUpperCase() + prayerName.slice(1), '', '', prayerDate, prayerDate);
                }
            }
        }

        cal.download('prayer_times');
    });
});