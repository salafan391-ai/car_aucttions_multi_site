import logging
import requests
import re
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)
car_damage_codes = {
    "X": "استبدال",          # 교환
    "W": "صاج / لحام",       # 판금/용접
    "C": "صدأ / تآكل",       # 부식
    "A": "خدش",              # 흠집
    "U": "نتوء / تعرج",      # 요철
    "T": "ضرر / تلف"         # 손상
}

generations_ar = {
  # Roman numerals
  'I':'الإصدار الأول',
  'II':'الإصدار الثاني',
  'III':'الإصدار الثالث',
  'IV':'الإصدار الرابع',
  'V':'الإصدار الخامس',
  'VI':'الإصدار السادس',
  'VII':'الإصدار السابع',
  'VIII':'الإصدار الثامن',
  'IX':'الإصدار التاسع',
  'X':'الإصدار العاشر',
  
  # Common generation formats
  '1st Generation':'الجيل الأول',
  '2nd Generation':'الجيل الثاني',
  '3rd Generation':'الجيل الثالث',
  '4th Generation':'الجيل الرابع',
  '5th Generation':'الجيل الخامس',
  '6th Generation':'الجيل السادس',
  '7th Generation':'الجيل السابع',
  '8th Generation':'الجيل الثامن',
  '9th Generation':'الجيل التاسع',
  '10th Generation':'الجيل العاشر',
  
  # Numeric formats
  '1':'الجيل الأول',
  '2':'الجيل الثاني',
  '3':'الجيل الثالث',
  '4':'الجيل الرابع',
  '5':'الجيل الخامس',
  '6':'الجيل السادس',
  '7':'الجيل السابع',
  '8':'الجيل الثامن',
  '9':'الجيل التاسع',
  '10':'الجيل العاشر',
  
  # Generation with G prefix
  'G1':'الجيل الأول',
  'G2':'الجيل الثاني',
  'G3':'الجيل الثالث',
  'G4':'الجيل الرابع',
  'G5':'الجيل الخامس',
  'G6':'الجيل السادس',
  'G7':'الجيل السابع',
  'G8':'الجيل الثامن',
  'G9':'الجيل التاسع',
  'G10':'الجيل العاشر',
  
  # Korean style generation names
  '1세대':'الجيل الأول',
  '2세대':'الجيل الثاني',
  '3세대':'الجيل الثالث',
  '4세대':'الجيل الرابع',
  '5세대':'الجيل الخامس',
  '6세대':'الجيل السادس',
  '7세대':'الجيل السابع',
  '8세대':'الجيل الثامن',
  '9세대':'الجيل التاسع',
  '10세대':'الجيل العاشر'
}


OPTION_DATA = [
  {
    "id": 22,
    "code": "001",
    "name_original": "브레이크 잠김 방지(ABS)",
    "name": "Brake Lock (ABS)",
    "sort": 22,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-4.png",
    "description": "It is a brake system that slides when the wheels are submerged when braked, or to prevent the driver from being able to properly control the direction of the car.",
    "location": "You can check the ABS module inside the engine room, and you can check the ABS warning lights on the instrument panel before the start of the start."
  },
  {
    "id": 23,
    "code": "019",
    "name_original": "미끄럼 방지(TCS)",
    "name": "Anti -slip (TCS)",
    "sort": 23,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-5.png",
    "description": "It is a system that controls the driving force of the vehicle so that the tire does not turn off when the vehicle departs and accelerates from a slippery road.",
    "location": "The TCS module is difficult to identify, but it can be checked by the TCS switch around the driver's seat, and can be checked with warning lights or setting functions of the instrument panel."
  },
  {
    "id": 55,
    "code": "022",
    "name_original": "열선시트(앞좌석)",
    "name": "Heated seats (front seats)",
    "sort": 55,
    "section": "04",
    "section_name": "Seats",
    "image": "https://m.encar.com/images/carsdata/option_images/option4-4.png",
    "description": "It is a function that warms the sheet with winter switch Onoff.",
    "location": "The front seats are located around the transmission or center fascia, and the rear seats are around the rear door window switch, rear air vent, and rear armrest. When the switch operation\nThe sheet warms up."
  },
  {
    "id": 1,
    "code": "010",
    "name_original": "선루프",
    "name": "Sunroof",
    "sort": 1,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-1.png",
    "description": "The car loop is made of glass and can be opened and closed.",
    "location": "The loop is made of glass and can be opened. Sometimes there is a glass -shaped glass loop where the loop is not opened, but the model is also a type of sunroof."
  },
  {
    "id": 7,
    "code": "017",
    "name_original": "알루미늄 휠",
    "name": "Aluminum wheel",
    "sort": 7,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-6.png",
    "description": "It is a wheel made of aluminum alloy and is lighter than a regular steel wheel.",
    "location": "General steel covers a plastic cover on the steel, but the aluminum wheel does not cover the cover and weighs light and is good for fuel economy. Distinguish from steel wheel\nAs a result, various methods such as chrome wheels, not steel wheels, are also checked with aluminum wheels."
  },
  {
    "id": 18,
    "code": "026",
    "name_original": "에어백(운전석)",
    "name": "Airbag (driver seat)",
    "sort": 18,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-1.png",
    "description": "It is a device that protects passengers from the shock when the vehicle collision and is a representative passenger protection device along with the seat belt.",
    "location": "The driver's seat can check the phrase equipped with an airbag in the center of the steering wheel."
  },
  {
    "id": 25,
    "code": "033",
    "name_original": "타이어 공기압센서(TPMS)",
    "name": "Tire Air Ap sensor (TPMS)",
    "sort": 25,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-7.png",
    "description": "It is a sensor that measures the air pressure on the four wheels of the vehicle and informs the driver as a warning. Since 2013, the new car model has been mandatory for cars and cars of 3.5 tons, and all new cars shipped from January 2015 have been mandatory.",
    "location": "There is a sensor inside the tire, but it is often difficult to check the naked eye, and it can be checked with the dashboard TMPS warning light."
  },
  {
    "id": 19,
    "code": "027",
    "name_original": "에어백(동승석)",
    "name": "Airbag (passenger seat)",
    "sort": 19,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-1.png",
    "description": "It is a device that protects passengers from the shock when the vehicle collision and is a representative passenger protection device along with the seat belt.",
    "location": "The driver's seat can check the phrase equipped with an airbag in the center of the steering wheel."
  },
  {
    "id": 20,
    "code": "020",
    "name_original": "에어백(사이드)",
    "name": "Airbag (side)",
    "sort": 20,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-2.png",
    "description": "It is a side airbag mounted on the driver's seat and passenger seat to protect the side of the occupant when the vehicle collides.",
    "location": "It is mounted on the driver's seat and the seat of the outside seat, which can be checked with the phrase."
  },
  {
    "id": 21,
    "code": "056",
    "name_original": "에어백(커튼)",
    "name": "Airbag (curtain)",
    "sort": 21,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-3.png",
    "description": "It is a curtain airbag that extends along the window to protect the head of the passenger when the vehicle's side collision.",
    "location": "It is usually mounted on the inside of the vehicle, and the airbag phrase is engraved on the side of the filler."
  },
  {
    "id": 29,
    "code": "032",
    "name_original": "주차감지센서(후방)",
    "name": "Parking sensor (rear)",
    "sort": 29,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-10.png",
    "description": "It is a system that detects obstacles with a sensor mounted on the front bumper and rear bumper in parking and slowing, and informs the driver with a beep or monitor.",
    "location": "The car bumper is usually mounted from 2 to 4 sensors, so you can check with the naked eye."
  },
  {
    "id": 8,
    "code": "062",
    "name_original": "루프랙",
    "name": "Roof rack",
    "sort": 8,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-7.png",
    "description": "It is called a roof rack or roofrail with two rods installed vertically to load the luggage on the roof of the vehicle or use it for fixing.",
    "location": "You can see with two rails or rods installed vertically on the loop of the vehicle."
  },
  {
    "id": 26,
    "code": "088",
    "name_original": "차선이탈 경보 시스템(LDWS)",
    "name": "Lane departure alarm system (LDWS)",
    "sort": 26,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-8.png",
    "description": "If you leave the lane without a turning light, it will inform the driver with a beep and traffic, and depends on the model, but it may vibrate the steering wheel to inform the driver.",
    "location": "You can check the switch or instrument panel around the driver's seat. The radar is attached to the front glass behind the room mirror, and the warning signal flashing or warning sound is given according to the specifications.\nSome vehicles are forced to maintain lanes or vibrate in the steering wheel. If you have a basic warning signal or a warning sound, you can check it as an option."
  },
  {
    "id": 27,
    "code": "002",
    "name_original": "전자제어 서스펜션(ECS)",
    "name": "Electronic control suspension (ECS)",
    "sort": 27,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-9.png",
    "description": "It is a device that automatically adjusts driving safety and ride comfort by adjusting the height or damping force of the vehicle by entering the computer according to the driving environment. Types include electronic control air suspension, active damper suspension, and active preview suspension.",
    "location": "It works through a lot of parts such as the structure and sensor of the shock absorber, but it is difficult to check with the naked eye. Some vehicles have a switch depending on the vehicle, and the electronic control suspension has the ability to adjust the damping force of the suspension, and the garage adjustment.  If one of the two functions is met, check it as an electronic control suspension option."
  },
  {
    "id": 28,
    "code": "085",
    "name_original": "주차감지센서(전방)",
    "name": "Parking Sensor (front)",
    "sort": 28,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-10.png",
    "description": "It is a system that detects obstacles with a sensor mounted on the front bumper and rear bumper in parking and slowing, and informs the driver with a beep or monitor.",
    "location": "The car bumper is usually mounted from 2 to 4 sensors, so you can check with the naked eye."
  },
  {
    "id": 31,
    "code": "058",
    "name_original": "후방 카메라",
    "name": "Rear camera",
    "sort": 31,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-12.png",
    "description": "It is a function that allows you to check the rear through the monitor when parking and backward by mounting a camera around the trunk or license plate.",
    "location": "If you put it in the backward gear R position, you can check it in the monitor or room mirror in the center fascia."
  },
  {
    "id": 41,
    "code": "097",
    "name_original": "오토 라이트",
    "name": "Auto light",
    "sort": 41,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-8.png",
    "description": "It is an automatic ON/OFF control by detecting the darkness around the tunnel or surroundings without manually operating the vehicle's lights.",
    "location": "You can check the headlamps around the steering wheel. There is an AUTO button and a sensor in front of the dashboard."
  },
  {
    "id": 49,
    "code": "072",
    "name_original": "USB 단자",
    "name": "USB terminal",
    "sort": 49,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-15.png",
    "description": "It is a terminal that allows you to watch the music of portable devices such as MP3 and PMP through an external input via USB connection jack in the audio of the vehicle.",
    "location": "The USB terminal is mostly at the bottom of the center fascia and is in some console boxes."
  },
  {
    "id": 2,
    "code": "029",
    "name_original": "헤드램프(HID)",
    "name": "Head Lamp (HID)",
    "sort": 2,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-2.png",
    "description": "HID/LED headlamps are more colored compared to normal halogen, so they don't get fatigue.",
    "location": "The color is closer to natural light than the halogen lamp, so it is identified by the naked eye, and the HID is confirmed by ballast and difficult to identify on the outside.\nLEDs have a design of several, not one, and some models with the Light Cover LED logo. In the case of a high -end version, the laser is also checked with the LED headlamp option."
  },
  {
    "id": 10,
    "code": "083",
    "name_original": "전동 조절 스티어링 휠",
    "name": "Electric control steering wheel",
    "sort": 10,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-9.png",
    "description": "The steering wheel allows you to adjust the tilt and telescopic with electricity to place the right position for the driver.",
    "location": "The steering wheel adjustment switch can check the features that can be adjusted inside the steering wheel."
  },
  {
    "id": 11,
    "code": "084",
    "name_original": "패들 시프트",
    "name": "Paddle shift",
    "sort": 11,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-10.png",
    "description": "The lever or button is mounted near the steering wheel for gear shifting, and some electric and hybrid cars can adjust the sensitivity of regenerative braking.",
    "location": "It is centered left and right around the steering wheel, and there is also a buttons."
  },
  {
    "id": 24,
    "code": "055",
    "name_original": "차체자세 제어장치(ESC)",
    "name": "Body posture control device (ESC)",
    "sort": 24,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-6.png",
    "description": "ABS and TCS are controlled if the ESC is a safety device for forward/backwards, when the understie or oversteer of the vehicle occurs during a sudden turn. Each manufacturer has a different name and the meaning is similar. We use various names such as ESP, VDC, and DSC.",
    "location": "You can check the switch or instrument panel around the driver's seat. In January 2012, it was mandatory for a passenger car and a complete new car with less than 4.5 tons.\nAnd the changed vehicle was mandatory in July 2014."
  },
  {
    "id": 36,
    "code": "094",
    "name_original": "전자식 주차브레이크(EPB)",
    "name": "Electronic parking brake (EPB)",
    "sort": 36,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-3.png",
    "description": "After parking the vehicle, it is a function that allows you to easily operate the parking brake with your fingers without locking it with your hands or feet. It is also possible to automatically terminate the brake, which can prevent the parking brakes from locking.",
    "location": "It is located around the driver's seat or transmission and works in a switch method."
  },
  {
    "id": 42,
    "code": "092",
    "name_original": "커튼/블라인드(뒷좌석)",
    "name": "Curtain/Blind (back seat)",
    "sort": 42,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-9.png",
    "description": "Curtain/Blind that blocks sunlight.",
    "location": "There is a device that can manually/automatically curtains around the door window of the rear seat.\nThere is a device that can be hit, and if it is automatic, there is a switch from the front and back."
  },
  {
    "id": 12,
    "code": "031",
    "name_original": "스티어링 휠 리모컨",
    "name": "Steering wheel remote control",
    "sort": 12,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-11.png",
    "description": "The button on the steering wheel allows you to conveniently operate audio and hands -free devices.",
    "location": "You can see that the steering wheel is equipped with a switch."
  },
  {
    "id": 13,
    "code": "030",
    "name_original": "ECM 룸미러",
    "name": "ECM room mirror",
    "sort": 13,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-12.png",
    "description": "It is a device that eliminates the driver with a room mirror by the headlights of the vehicle after driving at night.",
    "location": "The sensor in the mirror automatically prevents glare. You can check the original sensor at the top of the room mirror, and the frame lease room mirror is also available.\nPlease note that there are some things that can't be confirmed."
  },
  {
    "id": 14,
    "code": "074",
    "name_original": "하이패스",
    "name": "High pass",
    "sort": 14,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-13.png",
    "description": "When the Euro Expressway Tollgate is toll, the toll is automatically paid with a card built into the high pass terminal.",
    "location": "It is often built into the room mirror, and depending on some models or external construction methods, the dashboard may be different."
  },
  {
    "id": 15,
    "code": "006",
    "name_original": "파워 도어록",
    "name": "Power door lock",
    "sort": 15,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-14.png",
    "description": "If you lock the door lock switch in the driver's seat, all the doors are automatically closed.",
    "location": "Located near the left window switch on the left side of the driver's seat, you can see that you can open and close the entire door through the switch. If you have a certain speed and stop, there are some models that do not operate or cancel the lock."
  },
  {
    "id": 16,
    "code": "008",
    "name_original": "파워 스티어링 휠",
    "name": "Power steering wheel",
    "sort": 16,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-15.png",
    "description": "It is a feature that helps you to steer it easily by replenishing the steering wheel with other force. In the past, hydraulic type was used, but recently, it is a trend that uses electricity.",
    "location": "If the vehicle stops, it can be judged as a power steering wheel if it can be turned without difficulty when turning the steering wheel. Unless it is an old model model\nIt is mounted on most vehicles except some models such as Damas."
  },
  {
    "id": 17,
    "code": "007",
    "name_original": "파워 윈도우",
    "name": "Power Windows",
    "sort": 17,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-16.png",
    "description": "The glass window on the door can be easily opened with a switch.",
    "location": "The switch is mounted inside the door. Some vehicles are only a part of the car, and in the case of high -end options, some vehicles are up to one touch. If you can move Windows with a switch, check it with power window."
  },
  {
    "id": 9,
    "code": "082",
    "name_original": "열선 스티어링 휠",
    "name": "Thermal steering wheel",
    "sort": 9,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-8.png",
    "description": "It is a function that warms the cold steering wheel in winter.",
    "location": "There are most buttons in the steering wheel and center fascia."
  },
  {
    "id": 30,
    "code": "086",
    "name_original": "후측방 경보 시스템",
    "name": "Rear alarm system",
    "sort": 30,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-11.png",
    "description": "It is a feature that detects a vehicle approaching in the rear room (blind spot) when changing the lane while driving and informs the driver.",
    "location": "There is a rear alarm icon in the side mirror, and there may be a switch around the driver's seat."
  },
  {
    "id": 32,
    "code": "087",
    "name_original": "360도 어라운드 뷰",
    "name": "360 degree around view",
    "sort": 32,
    "section": "02",
    "section_name": "Safety",
    "image": "https://m.encar.com/images/carsdata/option_images/option2-13.png",
    "description": "It is a function that shows the area around the vehicle on a 360 -degree monitor in the parking and front slow, so it is easy to see the space and helps the parking and narrow places conveniently.",
    "location": "It is equipped with a camera outside the vehicle and you can check the view with the monitor. Some models may see a screen except for the front."
  },
  {
    "id": 33,
    "code": "068",
    "name_original": "크루즈 컨트롤(일반)",
    "name": "Cruise Control (General)",
    "sort": 33,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-1.png",
    "description": "When the driver sets the speed, it is a device that maintains the speed even if the driver does not pedal. Adaptive is an additional feature of the existing cruise control, which sets the speed and distance from the front car to automatically reduce the speed when the front car is reduced.",
    "location": "The cruise control can be checked around the steering wheel, the adaptive is a radar on the front of the vehicle and can be checked by the instrument panel setting. Adaptive is the option to set the distance between the car by defaulting to adjust the speed."
  },
  {
    "id": 39,
    "code": "015",
    "name_original": "무선도어 잠금장치",
    "name": "Wireless Door Lock",
    "sort": 39,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-6.png",
    "description": "It is a convenient device that can be locked/canceled with a wireless remote control without putting the key into the door.",
    "location": "The car key has a remote control button or a remote control with the key."
  },
  {
    "id": 40,
    "code": "081",
    "name_original": "레인센서",
    "name": "Rain sensor",
    "sort": 40,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-7.png",
    "description": "Detects rainwater falling in the front glass, and the wiper automatically wipes the windshield. The wiper speed is automatically adjusted according to the amount of rain.",
    "location": "You can check the wiper control switch around the steering wheel. There is an AUTO button and the sensor is sensor at the top of the front glass."
  },
  {
    "id": 34,
    "code": "079",
    "name_original": "크루즈 컨트롤(어댑티브)",
    "name": "Cruise control (adaptive)",
    "sort": 34,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-1.png",
    "description": "When the driver sets the speed, it is a device that maintains the speed even if the driver does not pedal. Adaptive is an additional feature of the existing cruise control, which sets the speed and distance from the front car to automatically reduce the speed when the front car is reduced.",
    "location": "The cruise control can be checked around the steering wheel, the adaptive is a radar on the front of the vehicle and can be checked by the instrument panel setting. Adaptive is the option to set the distance between the car by defaulting to adjust the speed."
  },
  {
    "id": 35,
    "code": "095",
    "name_original": "헤드업 디스플레이(HUD)",
    "name": "Head -up display (HUD)",
    "sort": 35,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-2.png",
    "description": "It is a function that projects the vehicle's information on the front glass of the driver to easily check the information (speed, navigation).",
    "location": "There is a device that can be projected with glass on the dashboard in front of the driver's seat, and there are also vehicles with switches around the driver's seat."
  },
  {
    "id": 37,
    "code": "023",
    "name_original": "자동 에어컨",
    "name": "Automatic air conditioner",
    "sort": 37,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-4.png",
    "description": "It is an air conditioner that maintains a constant temperature by automatically adjusting the air volume and temperature when setting the temperature that the user wants. In the case of dual full auto air conditioning, the temperature of the passenger seat can be adjusted independently.",
    "location": "The air conditioning system is located in the center fascia and has an AUTO button."
  },
  {
    "id": 38,
    "code": "057",
    "name_original": "스마트키",
    "name": "Smart key",
    "sort": 38,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-5.png",
    "description": "It is a convenience device that can terminate the door lock by just having a smart key or to start by pressing the button.",
    "location": "Smartki does not have a key shape in appearance, and there is a Keyless Go function that can be opened with a smart key and can be started (Keyless Entry).\nIf it is satisfied, check it with the options of the smart key."
  },
  {
    "id": 44,
    "code": "005",
    "name_original": "내비게이션",
    "name": "Navigation",
    "sort": 44,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-10.png",
    "description": "When you set up your destination, you will be provided with road guidance and traffic information on a monitor with a built -in GPS.",
    "location": "The center fascia is equipped with a monitor screen to confirm the location of the vehicle on the map and set the destination."
  },
  {
    "id": 45,
    "code": "004",
    "name_original": "앞좌석 AV 모니터",
    "name": "Front seat AV monitor",
    "sort": 45,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-11.png",
    "description": "It is a device with a video system such as TV and video inside the vehicle.",
    "location": "The center fascia is equipped with a monitor screen."
  },
  {
    "id": 46,
    "code": "054",
    "name_original": "뒷좌석 AV 모니터",
    "name": "Back seat AV monitor",
    "sort": 46,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-12.png",
    "description": "It is a device with a video system such as TV and video inside the vehicle.",
    "location": "It is often installed behind the front seat seats, and some models are also mounted on the front seat armrest and loop."
  },
  {
    "id": 3,
    "code": "075",
    "name_original": "헤드램프(LED)",
    "name": "Head Lamp (LED)",
    "sort": 3,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-2.png",
    "description": "HID/LED headlamps are more colored compared to normal halogen, so they don't get fatigue.",
    "location": "The color is closer to natural light than the halogen lamp, so it is identified by the naked eye, and the HID is confirmed by ballast and difficult to identify on the outside.\nLEDs have a design of several, not one, and some models with the Light Cover LED logo. In the case of a high -end version, the laser is also checked with the LED headlamp option."
  },
  {
    "id": 4,
    "code": "059",
    "name_original": "파워 전동 트렁크",
    "name": "Power electric trunk",
    "sort": 4,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-3.png",
    "description": "It is a function that allows you to easily close the trunk with a switch without strength.",
    "location": "You can see the switch switch around the trunk line."
  },
  {
    "id": 5,
    "code": "080",
    "name_original": "고스트 도어 클로징",
    "name": "Ghost Door Closing",
    "sort": 5,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-4.png",
    "description": "Also called an electric power door system, even if the passenger does not close the door completely, the sensor attached to the inside of the door is detected to operate the motor to completely close the door.",
    "location": "Even if the door is not completely closed, it will be completely closed smoothly when it becomes until it is closed."
  },
  {
    "id": 6,
    "code": "024",
    "name_original": "전동접이 사이드 미러",
    "name": "Electric contacts side mirror",
    "sort": 6,
    "section": "01",
    "section_name": "Exterior/Interior",
    "image": "https://m.encar.com/images/carsdata/option_images/option1-5.png",
    "description": "It is a function that allows you to fold the side mirror with a narrow space or parking.",
    "location": "There are main switches around the driver's window window switch, and some tuned vehicles are folded without switches. Pressing the switch to fold and spread\nIf you meet one of the features that have a function or before and after starting, you can check the electric side mirror."
  },
  {
    "id": 43,
    "code": "093",
    "name_original": "커튼/블라인드(후방)",
    "name": "Curtain/Blind (rear)",
    "sort": 43,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-9.png",
    "description": "Curtain/Blind that blocks sunlight.",
    "location": "There is a device that can manually/automatically curtains around the door window of the rear seat.\nThere is a device that can be hit, and if it is automatic, there is a switch from the front and back."
  },
  {
    "id": 48,
    "code": "003",
    "name_original": "CD 플레이어",
    "name": "CD player",
    "sort": 48,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-14.png",
    "description": "It is a device that plays CDs stored in music.",
    "location": "It is located in the center fascia with players or changers that can play CDs. In some cases, it may be installed in console boxes, trunks, etc."
  },
  {
    "id": 50,
    "code": "071",
    "name_original": "AUX 단자",
    "name": "AUX terminal",
    "sort": 50,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-16.png",
    "description": "It is a terminal that allows you to watch the music of portable devices such as MP3 and PMP through external input through the AUX connection jack in the audio of the vehicle.",
    "location": "The AUX terminal is mostly at the bottom of the center fascia and is in some console boxes."
  },
  {
    "id": 51,
    "code": "014",
    "name_original": "가죽시트",
    "name": "Leather sheet",
    "sort": 51,
    "section": "04",
    "section_name": "Seats",
    "image": "https://m.encar.com/images/carsdata/option_images/option4-1.png",
    "description": "The seat material of the vehicle is used as a leather sheet used as a material of leather, suede and fabric+leather mixing.",
    "location": "You can see the material of the sheet made of leather or leather, not fabrics. Depending on the specifications, there are many types of sheets mixed with artificial, natural, suede, and fabrics.\nRegardless of the type, check with leather seats."
  },
  {
    "id": 52,
    "code": "021",
    "name_original": "전동시트(운전석)",
    "name": "Electric sheet (driver seat)",
    "sort": 52,
    "section": "04",
    "section_name": "Seats",
    "image": "https://m.encar.com/images/carsdata/option_images/option4-2.png",
    "description": "The switch is a function that allows you to adjust the height of the sheet, front and back, and backrep to the desired location.",
    "location": "There is a switch under the sheet or the door, and there is an electric sheet with no functional functions in the height, front and rear, and backrests. If one of the three functions meets\nCheck it with an electric seat option."
  },
  {
    "id": 53,
    "code": "035",
    "name_original": "전동시트(동승석)",
    "name": "Electric sheet (passenger seat)",
    "sort": 53,
    "section": "04",
    "section_name": "Seats",
    "image": "https://m.encar.com/images/carsdata/option_images/option4-2.png",
    "description": "The switch is a function that allows you to adjust the height of the sheet, front and back, and backrep to the desired location.",
    "location": "There is a switch under the sheet or the door, and there is an electric sheet with no functional functions in the height, front and rear, and backrests. If one of the three functions meets\nCheck it with an electric seat option."
  },
  {
    "id": 54,
    "code": "089",
    "name_original": "전동시트(뒷좌석)",
    "name": "Electric sheet (back seat)",
    "sort": 54,
    "section": "04",
    "section_name": "Seats",
    "image": "https://m.encar.com/images/carsdata/option_images/option4-3.png",
    "description": "It is usually available in large cars, and the switch is a function that allows you to adjust the height of the sheet, front and rear, and backrest to the desired location.",
    "location": "You can check the switch in the rear door or center armrest. A vehicle that adjusts folding such as SUVs with an electric switch can also be viewed as a rear electric sheet."
  },
  {
    "id": 47,
    "code": "096",
    "name_original": "블루투스",
    "name": "Bluetooth",
    "sort": 47,
    "section": "03",
    "section_name": "Convenience/Multimedia",
    "image": "https://m.encar.com/images/carsdata/option_images/option3-13.png",
    "description": "It is a function that allows you to connect your smartphone with audio, which is the Bluetooth function of the vehicle, and use various files and information such as telephone and music.",
    "location": "You can check the function in the audio settings. Bluetooth has audio streaming features that can listen to music and hands -free available for calling. One of the two functions\nIf it is met, check it with the Bluetooth option. In the process of constructing some navigation, the function may be lost, so please check the normal operation."
  },
  {
    "id": 56,
    "code": "063",
    "name_original": "열선시트(뒷좌석)",
    "name": "Heating sheet (back seat)",
    "sort": 56,
    "section": "04",
    "section_name": "Seats",
    "image": "https://m.encar.com/images/carsdata/option_images/option4-4.png",
    "description": "It is a function that warms the sheet with winter switch Onoff.",
    "location": "The front seats are located around the transmission or center fascia, and the rear seats are around the rear door window switch, rear air vent, and rear armrest. When the switch operation\nThe sheet warms up."
  },
  {
    "id": 57,
    "code": "051",
    "name_original": "메모리 시트(운전석)",
    "name": "Memory sheet (driver)",
    "sort": 57,
    "section": "04",
    "section_name": "Seats",
    "image": "https://m.encar.com/images/carsdata/option_images/option4-5.png",
    "description": "It is a function that fixes the sheet in a comfortable position for the driver's seat and passenger seat and sets the location to remember it comfortably with the button. And you can use it conveniently when other drivers manipulate the seating position differently.",
    "location": "Located at the bottom of the door trim or the sheet, and setting and specifying the number, the contents of the adjusted sheet are stored."
  },
  {
    "id": 58,
    "code": "078",
    "name_original": "메모리 시트(동승석)",
    "name": "Memory sheet (passenger seat)",
    "sort": 58,
    "section": "04",
    "section_name": "Seats",
    "image": "https://m.encar.com/images/carsdata/option_images/option4-5.png",
    "description": "It is a function that fixes the sheet in a comfortable position for the driver's seat and passenger seat and sets the location to remember it comfortably with the button. And you can use it conveniently when other drivers manipulate the seating position differently.",
    "location": "Located at the bottom of the door trim or the sheet, and setting and specifying the number, the contents of the adjusted sheet are stored."
  },
  {
    "id": 59,
    "code": "034",
    "name_original": "통풍시트(운전석)",
    "name": "Ventilation sheet (driver)",
    "sort": 59,
    "section": "04",
    "section_name": "Seats",
    "image": "https://m.encar.com/images/carsdata/option_images/option4-6.png",
    "description": "In hot weather, the hips that do not reach the air conditioner are operated to operate the ventilation seat switch to circulate the cool air to the sheet to remove the heat to maintain the comfort.",
    "location": "Located around the transmission or center fascia, the cool air is felt when the switch is operated."
  },
  {
    "id": 60,
    "code": "077",
    "name_original": "통풍시트(동승석)",
    "name": "Gout Sheet (Dongseungseok)",
    "sort": 60,
    "section": "04",
    "section_name": "Seats",
    "image": "https://m.encar.com/images/carsdata/option_images/option4-6.png",
    "description": "In hot weather, the hips that do not reach the air conditioner are operated to operate the ventilation seat switch to circulate the cool air to the sheet to remove the heat to maintain the comfort.",
    "location": "Located around the transmission or center fascia, the cool air is felt when the switch is operated."
  },
  {
    "id": 61,
    "code": "090",
    "name_original": "통풍시트(뒷좌석)",
    "name": "Ventilation sheet (back seat)",
    "sort": 61,
    "section": "04",
    "section_name": "Seats",
    "image": "https://m.encar.com/images/carsdata/option_images/option4-7.png",
    "description": "In the rear seats, a separate ventilation sheet functions to operate the hip switch that does not reach the air conditioner in hot weather to circulate the cool air on the sheet to control the heat to maintain comfort.",
    "location": "Rear Door Windows Switch, Rear Air Vent, Rear Armrest is around, and cool air is felt when the switch is operated."
  },
  {
    "id": 62,
    "code": "091",
    "name_original": "마사지 시트",
    "name": "Massage sheet",
    "sort": 62,
    "section": "04",
    "section_name": "Seats",
    "image": "https://m.encar.com/images/carsdata/option_images/option4-8.png",
    "description": "It is also called a massage sheet, and the massage function is added to the car seat to relieve fatigue.",
    "location": "It has a function in the front and rear seats and some of the rear seats, and when the switch is operated, you can see whether the massage is operated by the backrest by air tube."
  }
]



# Multi-language option codes mapping based on the JSON data
OPTION_TRANSLATIONS = {
    # English translations
    'en': {
        '001': 'Brake Lock (ABS)',
        '002': 'Electronic control suspension (ECS)',
        '003': 'CD player',
        '004': 'Front seat AV monitor',
        '005': 'Navigation',
        '006': 'Power door lock',
        '007': 'Power Windows',
        '008': 'Power steering wheel',
        '010': 'Sunroof',
        '014': 'Leather sheet',
        '015': 'Wireless Door Lock',
        '017': 'Aluminum wheel',
        '019': 'Anti-slip (TCS)',
        '020': 'Airbag (side)',
        '021': 'Electric sheet (driver seat)',
        '022': 'Heated seats (front seats)',
        '023': 'Automatic air conditioner',
        '024': 'Electric contacts side mirror',
        '026': 'Airbag (driver seat)',
        '027': 'Airbag (passenger seat)',
        '029': 'Heated steering wheel',
        '030': 'ECM room mirror',
        '031': 'Steering wheel remote control',
        '032': 'Parking sensor (rear)',
        '033': 'Tire Air Ap sensor (TPMS)',
        '034': 'Ventilation sheet (driver)',
        '035': 'Electric sheet (passenger seat)',
        '051': 'Memory sheet (driver)',
        '054': 'Back seat AV monitor',
        '055': 'Body posture control device (ESC)',
        '056': 'Airbag (curtain)',
        '057': 'Smart key',
        '058': 'Rear camera',
        '059': 'Power electric trunk',
        '062': 'Roof rack',
        '063': 'Heating sheet (back seat)',
        '068': 'Cruise Control (General)',
        '071': 'AUX terminal',
        '072': 'USB terminal',
        '074': 'High pass',
        '075': 'Head Lamp (LED)',
        '077': 'Ventilation sheet (passenger seat)',
        '078': 'Memory sheet (passenger seat)',
        '079': 'Cruise control (adaptive)',
        '080': 'Ghost Door Closing',
        '081': 'Rain sensor',
        '082': 'Thermal steering wheel',
        '083': 'Electric control steering wheel',
        '084': 'Paddle shift',
        '085': 'Parking Sensor (front)',
        '086': 'Rear alarm system',
        '087': '360 degree around view',
        '088': 'Lane departure alarm system (LDWS)',
        '089': 'Electric sheet (back seat)',
        '090': 'Ventilation sheet (back seat)',
        '091': 'Massage sheet',
        '092': 'Curtain/Blind (back seat)',
        '093': 'Curtain/Blind (rear)',
        '094': 'Electronic parking brake (EPB)',
        '095': 'Head-up display (HUD)',
        '096': 'Bluetooth',
        '097': 'Auto light',
    },
    # Arabic translations
    'ar': {
        '001': 'نظام منع انغلاق المكابح (ABS)',
        '002': 'نظام تعليق إلكتروني (ECS)',
        '003': 'مشغل أقراص مدمجة',
        '004': 'شاشة AV للمقاعد الأمامية',
        '005': 'نظام ملاحة',
        '006': 'قفل أبواب كهربائي',
        '007': 'نوافذ كهربائية',
        '008': 'عجلة قيادة كهربائية',
        '010': 'فتحة سقف',
        '014': 'مقاعد جلدية',
        '015': 'قفل أبواب لاسلكي',
        '017': 'عجلات ألومنيوم',
        '019': 'نظام منع الانزلاق (TCS)',
        '020': 'وسادة هوائية جانبية',
        '021': 'مقعد كهربائي (السائق)',
        '022': 'مقاعد مدفأة (المقاعد الأمامية)',
        '023': 'مكيف هواء أوتوماتيكي',
        '024': 'مرايا جانبية كهربائية قابلة للطي',
        '026': 'وسادة هوائية (مقعد السائق)',
        '027': 'وسادة هوائية (مقعد الراكب)',
        '029': 'عجلة قيادة مدفأة',
        '030': 'مرآة داخلية بخاصية التعتيم الإلكتروني',
        '031': 'أزرار تحكم على عجلة القيادة',
        '032': 'حساسات ركن خلفية',
        '033': 'نظام مراقبة ضغط الإطارات (TPMS)',
        '034': 'مقعد بخاصية التهوية (السائق)',
        '035': 'مقعد كهربائي (الراكب)',
        '051': 'مقعد بخاصية الذاكرة (السائق)',
        '054': 'شاشة AV للمقاعد الخلفية',
        '055': 'نظام التحكم الإلكتروني بالثبات (ESC)',
        '056': 'وسادة هوائية ستارية',
        '057': 'مفتاح ذكي',
        '058': 'كاميرا خلفية',
        '059': 'صندوق أمتعة كهربائي',
        '062': 'قضبان سقف',
        '063': 'مقاعد خلفية مدفأة',
        '068': 'مثبت سرعة (عادي)',
        '071': 'منفذ AUX',
        '072': 'منفذ USB',
        '074': 'نظام دفع رسوم المرور',
        '075': 'مصابيح أمامية LED',
        '077': 'مقعد بخاصية التهوية (الراكب)',
        '078': 'مقعد بخاصية الذاكرة (الراكب)',
        '079': 'مثبت سرعة متكيف',
        '080': 'إغلاق أبواب آلي',
        '081': 'حساس مطر',
        '082': 'عجلة قيادة مدفأة',
        '083': 'عجلة قيادة قابلة للتعديل كهربائياً',
        '084': 'مبدل سرعات على عجلة القيادة',
        '085': 'حساسات ركن أمامية',
        '086': 'نظام تنبيه المنطقة الخلفية',
        '087': 'رؤية محيطية 360 درجة',
        '088': 'نظام التنبيه عند مغادرة المسار (LDWS)',
        '089': 'مقعد كهربائي (المقاعد الخلفية)',
        '090': 'مقاعد خلفية بخاصية التهوية',
        '091': 'مقعد بخاصية التدليك',
        '092': 'ستائر/حاجب شمس (المقاعد الخلفية)',
        '093': 'ستائر/حاجب شمس (خلفي)',
        '094': 'فرامل يد إلكترونية (EPB)',
        '095': 'شاشة عرض أمامية (HUD)',
        '096': 'بلوتوث',
        '097': 'إضاءة أوتوماتيكية',
    }
}

# Default to English for backward compatibility
STANDARD_OPTIONS = OPTION_TRANSLATIONS['en']

def get_option_data(option_code):
    """
    Get the option data for a given option code
    
    Args:
        option_code (str): The option code to lookup
        
    Returns:
        dict: The option data dictionary or None if not found
    """
    for option in OPTION_DATA:
        if option['code'] == option_code:
            return option
    return None

def get_option_description(option_code, language='en'):
    """
    Get the description for a given option code in the specified language
    
    Args:
        option_code (str): The option code to lookup
        language (str): The language code ('en' for English, 'ar' for Arabic)
        
    Returns:
        dict: A dictionary with option details including name, description, and location
    """
    # Get the option data from OPTION_DATA
    option_data = get_option_data(option_code)
    
    if option_data:
        # For Arabic language
        if language == 'ar':
            # Use Arabic translations if available, otherwise use English
            ar_name = OPTION_TRANSLATIONS['ar'].get(option_code, option_data['name'])
            return {
                'name': ar_name,
                'description': option_data.get('description', ''),
                'location': option_data.get('location', ''),
                'image': option_data.get('image', ''),
                'section': option_data.get('section', ''),
                'section_name': option_data.get('section_name', '')
            }
        # For English or any other language
        else:
            return {
                'name': option_data['name'],
                'description': option_data.get('description', ''),
                'location': option_data.get('location', ''),
                'image': option_data.get('image', ''),
                'section': option_data.get('section', ''),
                'section_name': option_data.get('section_name', '')
            }
    
    # Fallback to the old method if not found in OPTION_DATA
    if language not in OPTION_TRANSLATIONS:
        language = 'en'  # Default to English if language not supported
    
    option_name = OPTION_TRANSLATIONS[language].get(option_code, f"Option {option_code}")
    return {
        'name': option_name,
        'description': '',
        'location': '',
        'image': '',
        'section': '',
        'section_name': ''
    }

def format_options_list(options_list, language='en'):
    """
    Format a list of option codes into a list of descriptions in the specified language
    
    Args:
        options_list (list): List of option codes
        language (str): The language code ('en' for English, 'ar' for Arabic)
        
    Returns:
        list: List of option descriptions in the specified language
    """
    if not options_list or not isinstance(options_list, list):
        return []
    
    # Return the option name strings for backward compatibility
    if language == 'ar':
        return [OPTION_TRANSLATIONS['ar'].get(code, f"Option {code}") for code in options_list]
    else:
        return [OPTION_TRANSLATIONS['en'].get(code, f"Option {code}") for code in options_list]

def enrich_car_details_from_db(car_data, language='en'):
    """
    Enrich car data with additional information like option descriptions from the database
    
    Args:
        car_data (dict): The car data to enrich
        language (str): The language code ('en' for English, 'ar' for Arabic)
        
    Returns:
        dict: The enriched car data
    """
    # Import here to avoid circular imports
    from cars.models import Option
    
    if not car_data or not isinstance(car_data, dict):
        return car_data
    
    # Check if car has lots and details with options
    if 'lots' in car_data and car_data['lots'] and len(car_data['lots']) > 0:
        lot = car_data['lots'][0]
        
        if 'details' in lot and 'options' in lot['details']:
            options = lot['details']['options']
            
            # Enrich standard options with descriptions from database
            if 'standard' in options and isinstance(options['standard'], list):
                # Create a list of dictionaries with both English and Arabic translations
                standard_options = []
                for code in options['standard']:
                    # Get the option data from the database
                    try:
                        option_obj = Option.objects.get(code=code)
                        standard_options.append({
                            'code': code,
                            'image': option_obj.image,
                            'section': option_obj.section,
                            'section_name': option_obj.section_name,
                            'en': {
                                'name': option_obj.name,
                                'description': option_obj.description,
                                'location': option_obj.location
                            },
                            'ar': {
                                'name': option_obj.name_ar,
                                'description': option_obj.description_ar,
                                'location': option_obj.location_ar
                            }
                        })
                    except Option.DoesNotExist:
                        # Fallback to the old method if option not in database
                        standard_options.append({
                            'code': code,
                            'en': get_option_description(code, 'en'),
                            'ar': get_option_description(code, 'ar')
                        })
                options['standard_options'] = standard_options
            
            # Enrich additional options with descriptions from database
            if 'etc' in options and isinstance(options['etc'], list):
                # Create a list of dictionaries with both English and Arabic translations
                etc_options = []
                for code in options['etc']:
                    # Get the option data from the database
                    try:
                        option_obj = Option.objects.get(code=code)
                        etc_options.append({
                            'code': code,
                            'image': option_obj.image,
                            'section': option_obj.section,
                            'section_name': option_obj.section_name,
                            'en': {
                                'name': option_obj.name,
                                'description': option_obj.description,
                                'location': option_obj.location
                            },
                            'ar': {
                                'name': option_obj.name_ar,
                                'description': option_obj.description_ar,
                                'location': option_obj.location_ar
                            }
                        })
                    except Option.DoesNotExist:
                        # Fallback to the old method if option not in database
                        etc_options.append({
                            'code': code,
                            'en': get_option_description(code, 'en'),
                            'ar': get_option_description(code, 'ar')
                        })
                options['etc_options'] = etc_options
            
            # Enrich tuning options with descriptions from database
            if 'tuning' in options and isinstance(options['tuning'], list):
                # Create a list of dictionaries with both English and Arabic translations
                tuning_options = []
                for code in options['tuning']:
                    # Get the option data from the database
                    try:
                        option_obj = Option.objects.get(code=code)
                        tuning_options.append({
                            'code': code,
                            'image': option_obj.image,
                            'section': option_obj.section,
                            'section_name': option_obj.section_name,
                            'en': {
                                'name': option_obj.name,
                                'description': option_obj.description,
                                'location': option_obj.location
                            },
                            'ar': {
                                'name': option_obj.name_ar,
                                'description': option_obj.description_ar,
                                'location': option_obj.location_ar
                            }
                        })
                    except Option.DoesNotExist:
                        # Fallback to the old method if option not in database
                        tuning_options.append({
                            'code': code,
                            'en': get_option_description(code, 'en'),
                            'ar': get_option_description(code, 'ar')
                        })
                options['tuning_options'] = tuning_options
                
            # Keep the old format for backward compatibility
            if 'standard' in options and isinstance(options['standard'], list):
                options['standard_descriptions'] = format_options_list(options['standard'], language)
                options['standard_descriptions_ar'] = format_options_list(options['standard'], 'ar')
            
            if 'etc' in options and isinstance(options['etc'], list):
                options['etc_descriptions'] = format_options_list(options['etc'], language)
                options['etc_descriptions_ar'] = format_options_list(options['etc'], 'ar')
            
            if 'tuning' in options and isinstance(options['tuning'], list):
                options['tuning_descriptions'] = format_options_list(options['tuning'], language)
                options['tuning_descriptions_ar'] = format_options_list(options['tuning'], 'ar')
    
    return car_data


def enrich_car_details(car_data, language='en'):
    """
    Enrich car data with additional information like option descriptions in the specified language
    
    Args:
        car_data (dict): The car data to enrich
        language (str): The language code ('en' for English, 'ar' for Arabic)
        
    Returns:
        dict: The enriched car data
    """
    if not car_data or not isinstance(car_data, dict):
        return car_data
    
    # Check if car has lots and details with options
    if 'lots' in car_data and car_data['lots'] and len(car_data['lots']) > 0:
        lot = car_data['lots'][0]
        
        if 'details' in lot and 'options' in lot['details']:
            options = lot['details']['options']
            
            # Enrich standard options with descriptions in English and Arabic
            if 'standard' in options and isinstance(options['standard'], list):
                # Create a list of dictionaries with both English and Arabic translations
                standard_options = []
                for code in options['standard']:
                    # Get the option data directly from OPTION_DATA
                    option_data = get_option_data(code)
                    if option_data:
                        standard_options.append({
                            'code': code,
                            'en': get_option_description(code, 'en'),
                            'ar': get_option_description(code, 'ar'),
                            'image': option_data.get('image', ''),
                            'section': option_data.get('section', ''),
                            'section_name': option_data.get('section_name', '')
                        })
                    else:
                        standard_options.append({
                            'code': code,
                            'en': get_option_description(code, 'en'),
                            'ar': get_option_description(code, 'ar')
                        })
                options['standard_options'] = standard_options
            
            # Enrich additional options with descriptions in English and Arabic
            if 'etc' in options and isinstance(options['etc'], list):
                # Create a list of dictionaries with both English and Arabic translations
                etc_options = []
                for code in options['etc']:
                    # Get the option data directly from OPTION_DATA
                    option_data = get_option_data(code)
                    if option_data:
                        etc_options.append({
                            'code': code,
                            'en': get_option_description(code, 'en'),
                            'ar': get_option_description(code, 'ar'),
                            'image': option_data.get('image', ''),
                            'section': option_data.get('section', ''),
                            'section_name': option_data.get('section_name', '')
                        })
                    else:
                        etc_options.append({
                            'code': code,
                            'en': get_option_description(code, 'en'),
                            'ar': get_option_description(code, 'ar')
                        })
                options['etc_options'] = etc_options
            
            # Enrich tuning options with descriptions in English and Arabic
            if 'tuning' in options and isinstance(options['tuning'], list):
                # Create a list of dictionaries with both English and Arabic translations
                tuning_options = []
                for code in options['tuning']:
                    # Get the option data directly from OPTION_DATA
                    option_data = get_option_data(code)
                    if option_data:
                        tuning_options.append({
                            'code': code,
                            'en': get_option_description(code, 'en'),
                            'ar': get_option_description(code, 'ar'),
                            'image': option_data.get('image', ''),
                            'section': option_data.get('section', ''),
                            'section_name': option_data.get('section_name', '')
                        })
                    else:
                        tuning_options.append({
                            'code': code,
                            'en': get_option_description(code, 'en'),
                            'ar': get_option_description(code, 'ar')
                        })
                options['tuning_options'] = tuning_options
                
            # Keep the old format for backward compatibility
            if 'standard' in options and isinstance(options['standard'], list):
                options['standard_descriptions'] = format_options_list(options['standard'], language)
                options['standard_descriptions_ar'] = format_options_list(options['standard'], 'ar')
            
            if 'etc' in options and isinstance(options['etc'], list):
                options['etc_descriptions'] = format_options_list(options['etc'], language)
                options['etc_descriptions_ar'] = format_options_list(options['etc'], 'ar')
            
            if 'tuning' in options and isinstance(options['tuning'], list):
                options['tuning_descriptions'] = format_options_list(options['tuning'], language)
                options['tuning_descriptions_ar'] = format_options_list(options['tuning'], 'ar')
    
    return car_data
