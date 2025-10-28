# 🎨 Альтернативні теми для карти

Якщо Voyager Dark все ще надто темна, ось інші варіанти:

## 1. 🌓 Середня темна (рекомендую спробувати)

```javascript
// Alidade Smooth Dark - середня темна, дуже гарна контрастність
L.tileLayer('https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png', {
    attribution: '© Stadia Maps',
    maxZoom: 20,
}).addTo(map);
```

**Особливості:**
- Темно-синій фон (не чорний)
- Яскраві жовті дороги
- Яскраво-блакитна вода
- Відмінна контрастність

---

## 2. 🌙 Темна з кольоровими дорогами

```javascript
// Positron (темна версія)
L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/dark_nolabels/{z}/{x}/{y}{r}.png', {
    attribution: '© CARTO',
    maxZoom: 19,
}).addTo(map);

L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/dark_only_labels/{z}/{x}/{y}{r}.png', {
    maxZoom: 19,
}).addTo(map);
```

---

## 3. 🎨 Сіра (як Google Maps Dark)

```javascript
// Toner (темно-сіра, мінімалістична)
L.tileLayer('https://tiles.stadiamaps.com/tiles/stamen_toner/{z}/{x}/{y}{r}.png', {
    attribution: '© Stamen Design',
    maxZoom: 20,
}).addTo(map);
```

---

## 4. 🌃 Дуже темна (майже чорна)

```javascript
// Dark Matter (найтемніша)
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '© CARTO',
    maxZoom: 19,
}).addTo(map);
```

---

## 5. ☀️ Світла (якщо темна не підходить)

```javascript
// Positron (м'яка світла)
L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '© CARTO',
    maxZoom: 19,
}).addTo(map);
```

---

## 🔧 ЯК ЗМІНИТИ:

1. Відкрийте `/workspace/webapp/index.html`
2. Знайдіть рядок ~197 (Voyager Dark)
3. Замініть на один з варіантів вище
4. Збережіть
5. Скопіюйте на GitHub Pages

---

## 💡 МОЯ РЕКОМЕНДАЦІЯ:

Спробуйте **Alidade Smooth Dark** (#1) - це найкраща темна карта з відмінною контрастністю!
