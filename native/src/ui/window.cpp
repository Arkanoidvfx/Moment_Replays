#include "window.h"
#include "texts.h"
#include "obs/plugin.h"
#include "core/naming.h"

#include <QButtonGroup>
#include <QComboBox>
#include <QCoreApplication>
#include <QDateTime>
#include <QDesktopServices>
#include <QFileDialog>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QInputDialog>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QLocale>
#include <QMenu>
#include <QMessageBox>
#include <QPainter>
#include <QProcess>
#include <QRadioButton>
#include <QScrollArea>
#include <QSlider>
#include <QStackedWidget>
#include <QTableWidget>
#include <QTimer>
#include <QUrl>
#include <QVBoxLayout>
#include <QWidgetAction>

namespace mr {
namespace {

// Segoe Fluent Icons (Windows 11) / Segoe MDL2 Assets (Windows 10): the same code points.
enum Glyph : ushort {
	G_HOME = 0xE80F, G_FOLDER = 0xE8B7, G_NAMING = 0xE8AC, G_KEYBOARD = 0xE765, G_SOUND = 0xE767, G_GAME = 0xE7FC,
	G_SYNC = 0xE895, G_RECORD = 0xE7C8, G_VIDEO = 0xE714, G_WARNING = 0xE7BA, G_ERROR = 0xE783, G_OK = 0xE73E,
	G_PLAY = 0xE768, G_OPEN_FOLDER = 0xE838, G_CLOSE = 0xE8BB, G_ADD = 0xE710, G_INFO = 0xE946, G_CUT = 0xE8C6,
	G_FLAG = 0xE7C1, G_SAVE = 0xE74E, G_DOWNLOAD = 0xE896, G_MOVE = 0xE8DE, G_FORWARD = 0xE72A,
};

struct Look {
	QColor window, card, line, strong, text, muted, accent, ok, warn, bad;
};

Look look_of(const QWidget *widget)
{
	QPalette p = widget->palette();
	Look l;
	l.window = p.color(QPalette::Window);
	bool dark = l.window.lightness() < 128;
	l.card = dark ? l.window.lighter(132) : l.window.darker(104);
	l.line = dark ? l.window.lighter(175) : l.window.darker(118);
	l.strong = dark ? l.window.lighter(290) : l.window.darker(150);
	l.text = p.color(QPalette::WindowText);
	l.muted = QColor((l.text.red() * 6 + l.window.red() * 4) / 10, (l.text.green() * 6 + l.window.green() * 4) / 10,
			 (l.text.blue() * 6 + l.window.blue() * 4) / 10);
	l.accent = p.color(QPalette::Highlight);
	l.ok = dark ? QColor("#59D966") : QColor("#1E8528");
	l.warn = dark ? QColor("#EABC48") : QColor("#926E11");
	l.bad = dark ? QColor("#E85E75") : QColor("#C01C37");
	return l;
}

QFont icon_font(int px)
{
	QFont font;
	font.setFamilies({"Segoe Fluent Icons", "Segoe MDL2 Assets"});
	font.setPixelSize(px);
	return font;
}

QIcon glyph_icon(ushort code, const QColor &color, int px = 16)
{
	QPixmap pixmap(px * 2, px * 2);
	pixmap.fill(Qt::transparent);
	QPainter painter(&pixmap);
	painter.setFont(icon_font(px * 2));
	painter.setPen(color);
	painter.drawText(pixmap.rect(), Qt::AlignCenter, QString(QChar(code)));
	painter.end();
	pixmap.setDevicePixelRatio(2);
	return QIcon(pixmap);
}

// The font goes through the style sheet: OBS's theme sets a font for every widget and would win over setFont().
QString glyph_style(const QColor &color, int px)
{
	return QString("font-family:'Segoe Fluent Icons','Segoe MDL2 Assets';font-size:%1px;color:%2").arg(px).arg(color.name());
}

QLabel *glyph_label(ushort code, const QColor &color, int px = 16)
{
	auto *label = new QLabel(QString(QChar(code)));
	label->setFixedWidth(px + 4);
	label->setStyleSheet(glyph_style(color, px));
	return label;
}

void set_glyph(QLabel *label, ushort code, const QColor &color)
{
	label->setText(QString(QChar(code)));
	label->setStyleSheet(glyph_style(color, 16));
}

QString soft(QString text) // lets a long path wrap after each backslash
{
	return text.replace(QChar('\\'), QString(QChar('\\')) + QChar(0x200B));
}

QString qs(const std::string &text)
{
	return QString::fromStdString(text);
}

QString native(const std::string &path) // as Windows shows it, with a trailing separator for folders
{
	return QString::fromStdString(path).replace('/', '\\');
}

QFont mono()
{
	QFont font;
	font.setFamilies({"Cascadia Mono", "Consolas"});
	font.setPixelSize(12);
	return font;
}

class Card : public QFrame {
public:
	Card()
	{
		setObjectName("mrCard");
		box = new QVBoxLayout(this);
		box->setContentsMargins(0, 0, 0, 0);
		box->setSpacing(0);
	}
	void add(QWidget *row)
	{
		if (box->count()) {
			auto *line = new QFrame();
			line->setObjectName("mrLine");
			line->setFixedHeight(1);
			box->addWidget(line);
		}
		box->addWidget(row);
	}
	QVBoxLayout *box;
};

// One line of a card: optional icon, title with a muted line and a coloured note under it, controls on the right.
struct Row {
	QWidget *widget = nullptr;
	QLabel *icon = nullptr, *title = nullptr, *sub = nullptr, *note = nullptr;
	QHBoxLayout *controls = nullptr;
	QHBoxLayout *line = nullptr;

	void set_note(const QString &text, const QColor &color) const
	{
		note->setText(soft(text));
		note->setStyleSheet(QString("color:%1;font-size:12px").arg(color.name()));
		note->setVisible(!text.isEmpty());
	}
	void set_sub(const QString &text) const
	{
		sub->setText(soft(text));
		sub->setVisible(!text.isEmpty());
	}
};

Row make_row(const QString &title, const QString &sub = {}, ushort icon = 0, bool indent = false, const QColor &icon_color = {})
{
	Row row;
	row.widget = new QWidget();
	row.line = new QHBoxLayout(row.widget);
	row.line->setContentsMargins(indent ? 42 : 14, 9, 14, 9);
	row.line->setSpacing(12);
	if (icon) {
		row.icon = glyph_label(icon, icon_color.isValid() ? icon_color : row.widget->palette().color(QPalette::WindowText));
		row.line->addWidget(row.icon);
	}
	auto *texts = new QVBoxLayout();
	texts->setSpacing(1);
	row.title = new QLabel(title);
	row.title->setObjectName("mrRowTitle");
	row.title->setWordWrap(true);
	row.sub = new QLabel(soft(sub), row.widget);
	row.sub->setObjectName("mrSub");
	row.sub->setWordWrap(true);
	row.sub->setVisible(!sub.isEmpty());
	row.note = new QLabel();
	row.note->setWordWrap(true);
	row.note->setVisible(false);
	for (QLabel *label : {row.title, row.sub, row.note}) // never wider than the room the controls leave
		label->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
	texts->addWidget(row.title);
	texts->addWidget(row.sub);
	texts->addWidget(row.note);
	row.line->addLayout(texts, 1);
	row.controls = new QHBoxLayout();
	row.controls->setSpacing(8);
	row.line->addLayout(row.controls);
	row.widget->setMinimumHeight(48);
	return row;
}

QLabel *heading(const QString &text)
{
	auto *label = new QLabel(text);
	label->setObjectName("mrHeading");
	label->ensurePolished();
	const QFont base = label->font();
	label->setStyleSheet(base.pointSizeF() > 0 ? QString("font-size: %1pt").arg(base.pointSizeF() * 1.25)
						   : QString("font-size: %1px").arg(qRound(base.pixelSize() * 1.25)));
	label->setAlignment(Qt::AlignCenter);
	label->setContentsMargins(0, 10, 0, 2);
	return label;
}

QLabel *hint(const QString &text)
{
	auto *label = new QLabel(text);
	label->setObjectName("mrSub");
	label->setWordWrap(true);
	return label;
}

QLabel *key_label(const QString &text)
{
	auto *label = new QLabel(text);
	label->setObjectName("mrKey");
	label->setSizePolicy(QSizePolicy::Minimum, QSizePolicy::Fixed); // a key cap, not a box as tall as its row
	return label;
}

QPushButton *button(const QString &text, ushort icon = 0, const QWidget *for_colors = nullptr)
{
	auto *b = new QPushButton(text);
	if (icon && for_colors)
		b->setIcon(glyph_icon(icon, for_colors->palette().color(QPalette::ButtonText), 13));
	b->setAutoDefault(false);
	return b;
}

QWidget *page_of(const QString &title, QVBoxLayout *&body)
{
	auto *inner = new QWidget();
	inner->setObjectName("mrPage");
	body = new QVBoxLayout(inner);
	body->setContentsMargins(24, 20, 24, 24);
	body->setSpacing(8);
	auto *label = new QLabel(title);
	label->setObjectName("mrTitle");
	body->addWidget(label);
	body->addSpacing(4);
	auto *scroll = new QScrollArea();
	scroll->setObjectName("mrScroll");
	scroll->setWidgetResizable(true);
	scroll->setFrameShape(QFrame::NoFrame);
	scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
	scroll->setWidget(inner);
	return scroll;
}

QString ago(double wall, const QLocale &locale)
{
	qint64 seconds = QDateTime::currentSecsSinceEpoch() - (qint64)wall;
	if (seconds < 60)
		return T("just now");
	if (seconds < 3600)
		return T("%1 min ago").arg(seconds / 60);
	return locale.toString(QDateTime::fromSecsSinceEpoch((qint64)wall), QLocale::ShortFormat);
}

void show_in_folder(const QString &path)
{
	QProcess::startDetached("explorer.exe", {"/select,", QDir::toNativeSeparators(path)});
}

QString folder_problem_text(const FolderProblem &problem)
{
	if (problem.key == "folder_wrong_drive")
		return T("Wrong drive: OBS records to %1, so this folder must be on %1 too.").arg(qs(problem.drive));
	if (problem.key == "folder_not_found")
		return T("Not found. Connect the drive or choose another folder.");
	return T("Can't write to this folder. Choose another one.");
}

} // namespace

// ---------------------------------------------------------------- small widgets

ToggleSwitch::ToggleSwitch(QWidget *parent) : QAbstractButton(parent)
{
	setCheckable(true);
	setCursor(Qt::PointingHandCursor);
	setFixedSize(40, 20);
}

void ToggleSwitch::paintEvent(QPaintEvent *)
{
	Look look = look_of(this);
	QPainter painter(this);
	painter.setRenderHint(QPainter::Antialiasing);
	QRectF track = QRectF(rect()).adjusted(0.5, 0.5, -0.5, -0.5);
	painter.setPen(isChecked() ? look.accent : look.strong);
	painter.setBrush(isChecked() ? look.accent : look.window);
	painter.setOpacity(isEnabled() ? 1.0 : 0.45);
	painter.drawRoundedRect(track, 9.5, 9.5);
	painter.setPen(Qt::NoPen);
	painter.setBrush(isChecked() ? QColor(Qt::white) : look.muted);
	painter.drawEllipse(QPointF(isChecked() ? 30 : 10, 10), 6, 6);
	if (hasFocus()) {
		painter.setPen(look.text);
		painter.setBrush(Qt::NoBrush);
		painter.drawRoundedRect(track, 9.5, 9.5);
	}
}

KeyButton::KeyButton(Plugin *plugin_, std::string hotkey_, QWidget *parent)
	: QPushButton(parent), plugin(plugin_), hotkey(std::move(hotkey_))
{
	setObjectName("mrKeyButton");
	setMinimumWidth(150);
	setAutoDefault(false);
	connect(this, &QPushButton::clicked, this, [this] {
		capturing = true;
		setText(T("Press keys..."));
		setFocus();
	});
	show_binding();
}

void KeyButton::show_binding()
{
	if (capturing)
		return;
	QString text = qs(plugin->hotkey_text(hotkey));
	setText(text.isEmpty() ? T("No key") : text);
}

void KeyButton::keyPressEvent(QKeyEvent *event)
{
	if (!capturing) {
		QPushButton::keyPressEvent(event);
		return;
	}
	int key = event->key();
	if (key == Qt::Key_Control || key == Qt::Key_Shift || key == Qt::Key_Alt || key == Qt::Key_Meta)
		return; // waiting for the key itself
	capturing = false;
	if (key != Qt::Key_Escape) {
		obs_key_t obs_key = obs_key_from_virtual_key((int)event->nativeVirtualKey());
		if (obs_key != OBS_KEY_NONE) {
			json binding = {{"key", obs_key_to_name(obs_key)}};
			auto mods = event->modifiers();
			if (mods & Qt::ControlModifier)
				binding["control"] = true;
			if (mods & Qt::AltModifier)
				binding["alt"] = true;
			if (mods & Qt::ShiftModifier)
				binding["shift"] = true;
			if (mods & Qt::MetaModifier)
				binding["command"] = true;
			plugin->set_hotkey_bindings(hotkey, json::array({binding}));
		}
	}
	show_binding();
}

void KeyButton::focusOutEvent(QFocusEvent *event)
{
	capturing = false;
	show_binding();
	QPushButton::focusOutEvent(event);
}

// ---------------------------------------------------------------- the window

SettingsWindow::SettingsWindow(Plugin *plugin_, QWidget *parent) : QDialog(parent), plugin(plugin_)
{
	setObjectName("mrWindow");
	setWindowTitle("Moment Replays");
	setWindowFlag(Qt::WindowContextHelpButtonHint, false);
	resize(1060, 740);
	setMinimumSize(900, 560);
	build();
	connect(plugin, &Plugin::state_changed, this, [this] { refresh(); });
	auto *clock = new QTimer(this); // "2 min ago" and the live states
	connect(clock, &QTimer::timeout, this, [this] { refresh(); });
	clock->start(2000);
}

void SettingsWindow::commit(const std::function<void(Settings &)> &change)
{
	if (building)
		return;
	Settings next = plugin->settings();
	std::string language = next.interface_language;
	change(next);
	if (plugin->set_settings(next)) {
		QMessageBox::warning(this, "Moment Replays", T("This entry can't be used. Names can't contain < > / \\ | * ? : \" %"));
		QTimer::singleShot(0, this, [this] { build(); }); // back to what is saved
		return;
	}
	if (plugin->settings().interface_language != language && !rebuild_queued) {
		rebuild_queued = true; // not from inside the combo box's own signal
		QTimer::singleShot(0, this, [this] {
			rebuild_queued = false;
			build();
		});
	}
}

void SettingsWindow::refresh()
{
	if (building)
		return;
	for (auto &update : refreshers)
		update();
}

void SettingsWindow::build()
{
	building = true;
	refreshers.clear();
	if (layout()) {
		QLayoutItem *item;
		while ((item = layout()->takeAt(0))) {
			if (item->widget())
				item->widget()->deleteLater();
			delete item;
		}
		delete layout();
	}
	Look look = look_of(this);
	setStyleSheet(QString(R"(
		#mrWindow, #mrPage, #mrScroll, #mrScroll > QWidget > QWidget { background: %1; }
		#mrNav { background: %2; border-right: 1px solid %3; }
		QPushButton#mrNavButton { border: none; border-radius: 4px; padding: 8px 12px; text-align: left; background: transparent;
			color: %5; font-size: 13px; min-height: 20px; }
		QPushButton#mrNavButton:hover:!checked { background: %3; }
		QPushButton#mrNavButton:checked { background: %7; color: white; }
		QFrame#mrCard { background: %2; border: 1px solid %3; border-radius: 6px; }
		QFrame#mrBanner { background: %2; border: 1px solid %8; border-radius: 6px; }
		QFrame#mrLine { background: %3; border: none; }
		QLabel#mrTitle { font-size: 20px; font-weight: 600; }
		QLabel#mrHeading, QLabel#mrRowTitle { font-weight: 600; }
		QLabel#mrSub { color: %6; font-size: 12px; }
		QLabel#mrKey { border: 1px solid %4; border-radius: 4px; padding: 2px 8px; background: %1; font-size: 12px; }
		QPushButton#mrKeyButton { border: 1px solid %4; border-radius: 4px; padding: 4px 10px; background: %1; }
		QPushButton#mrKeyButton:focus { border-color: %7; }
		QPushButton#mrChip { border: none; border-radius: 4px; padding: 3px 8px; background: %3; font-size: 12px; min-height: 16px; }
	)")
			      .arg(look.window.name(), look.card.name(), look.line.name(), look.strong.name(), look.text.name(),
				   look.muted.name(), look.accent.name(), look.warn.name()));

	auto *root = new QHBoxLayout(this);
	root->setContentsMargins(0, 0, 0, 0);
	root->setSpacing(0);

	auto *nav = new QFrame();
	nav->setObjectName("mrNav");
	nav->setFixedWidth(216);
	auto *nav_box = new QVBoxLayout(nav);
	nav_box->setContentsMargins(8, 12, 8, 10);
	nav_box->setSpacing(2);
	pages = new QStackedWidget();
	auto *group = nav_group = new QButtonGroup(nav);

	struct Entry {
		ushort icon;
		QString title;
		QWidget *(SettingsWindow::*make)();
	};
	std::vector<Entry> entries = {
		{G_HOME, T("Overview"), &SettingsWindow::page_overview}, {G_FOLDER, T("Folders"), &SettingsWindow::page_folders},
		{G_NAMING, T("Naming"), &SettingsWindow::page_naming},   {G_KEYBOARD, T("Hotkeys"), &SettingsWindow::page_hotkeys},
		{G_SOUND, T("Sounds"), &SettingsWindow::page_sounds},    {G_GAME, T("Moments"), &SettingsWindow::page_moments},
		{G_SYNC, T("Updates"), &SettingsWindow::page_updates},
	};
	for (size_t i = 0; i < entries.size(); i++) {
		auto *item = new QPushButton(entries[i].title);
		item->setObjectName("mrNavButton");
		item->setCheckable(true);
		item->setAutoDefault(false);
		item->setIcon(glyph_icon(entries[i].icon, look.text));
		item->setIconSize(QSize(16, 16));
		group->addButton(item, (int)i);
		nav_box->addWidget(item);
		pages->addWidget((this->*entries[i].make)());
	}
	connect(group, &QButtonGroup::idClicked, this, [this](int id) {
		current_page = id;
		pages->setCurrentIndex(id);
		refresh();
	});
	group->button(current_page)->setChecked(true);
	pages->setCurrentIndex(current_page);
	nav_box->addStretch(1);

	auto *language = new QComboBox();
	language->setObjectName("mrLanguage");
	language->setAccessibleName(T("Interface language"));
	language->setIconSize(QSize(24, 16));
	language->setMaxVisibleItems(static_cast<int>(languages().size()));
	for (auto &[code, name] : languages())
		language->addItem(QIcon(qs(path_u8(plugin->env().data_dir / "flags" / (code + ".png")))), qs(name), qs(code));
	language->setCurrentIndex(std::max(0, language->findData(qs(plugin->settings().interface_language))));
	connect(language, &QComboBox::activated, this, [this, language](int index) {
		std::string code = language->itemData(index).toString().toStdString();
		commit([&](Settings &s) { s.interface_language = code; });
	});
	nav_box->addWidget(language);
	auto *version = hint(T("Version %1 on OBS %2").arg(VERSION, obs_get_version_string()));
	version->setContentsMargins(8, 0, 0, 0);
	nav_box->addWidget(version);

	root->addWidget(nav);
	root->addWidget(pages, 1);
	building = false;
	refresh();
}

void SettingsWindow::save_shots(const QString &folder)
{
	const char *names[] = {"1-overview", "2-folders", "3-naming", "4-hotkeys", "5-sounds", "6-moments", "7-updates"};
	for (int i = 0; i < 7; i++) {
		current_page = i;
		nav_group->button(i)->setChecked(true);
		pages->setCurrentIndex(i);
		refresh();
		QCoreApplication::processEvents();
		grab().save(QString("%1/%2.png").arg(folder, names[i]));
	}
	auto *language = findChild<QComboBox *>("mrLanguage");
	language->showPopup();
	QCoreApplication::processEvents();
	language->view()->window()->grab().save(folder + "/languages.png");
	language->hidePopup();
}

// Operates every kind of control the way a user would and puts each one back. The settings must come out as they
// went in. Buttons that open file dialogs are left alone.
std::string SettingsWindow::self_test()
{
	auto pump = [] {
		for (int i = 0; i < 3; i++)
			QCoreApplication::processEvents();
	};
	json before = plugin->settings().to_json();
	int toggles = 0, sliders = 0, radios = 0, keys = 0, pages_seen = 0;
	for (int page = 0; page < 7; page++) {
		nav_group->button(page)->click();
		pump();
		pages_seen++;
	}
	for (auto *toggle : findChildren<ToggleSwitch *>()) {
		toggle->click();
		pump();
		toggle->click();
		pump();
		toggles++;
	}
	for (auto *slider : findChildren<QSlider *>()) {
		int value = slider->value();
		slider->setValue(value == slider->maximum() ? value - 1 : value + 1);
		pump();
		slider->setValue(value);
		pump();
		sliders++;
	}
	QRadioButton *checked = nullptr;
	for (auto *radio : findChildren<QRadioButton *>())
		if (radio->isChecked())
			checked = radio;
	for (auto *radio : findChildren<QRadioButton *>()) {
		radio->click();
		pump();
		radios++;
	}
	if (checked)
		checked->click();
	pump();

	bool template_ok = true;
	for (auto *edit : findChildren<QLineEdit *>()) {
		if (edit->text().toStdString() != plugin->settings().clips_filename_template)
			continue;
		QString original = edit->text();
		edit->setText("%NAME_%Q"); // not a valid template: must not be saved
		pump();
		template_ok = plugin->settings().clips_filename_template == original.toStdString();
		edit->setText("%NAME_%H-%M");
		pump();
		template_ok = template_ok && plugin->settings().clips_filename_template == "%NAME_%H-%M";
		edit->setText(original);
		pump();
		break;
	}

	bool keys_ok = true;
	for (auto *key : findChildren<KeyButton *>()) {
		json old = plugin->hotkey_bindings(key->name());
		key->click();
		QKeyEvent press(QEvent::KeyPress, Qt::Key_F24, Qt::ControlModifier, 0, 0x87 /* VK_F24 */, 0);
		QCoreApplication::sendEvent(key, &press);
		pump();
		keys_ok = keys_ok && plugin->hotkey_text(key->name()) == "Ctrl + F24";
		plugin->set_hotkey_bindings(key->name(), old);
		pump();
		keys++;
	}

	bool table_ok = true;
	if (auto *table = findChild<QTableWidget *>(); table && table->rowCount()) {
		QString original = table->item(0, 1)->text();
		table->item(0, 1)->setText("Self Test Name");
		pump();
		auto &s = plugin->settings();
		table_ok = (s.app_name_replacements.size() && s.app_name_replacements[0].ends_with("> Self Test Name")) ||
			   (s.aliases_list.size() && s.aliases_list[0].ends_with("> Self Test Name"));
		Settings bad = plugin->settings(); // a refused entry: asked of the plugin directly, the window would show a warning box
		bad.app_other_names.push_back("C:\\path");
		table_ok = table_ok && plugin->set_settings(bad).has_value();
		findChild<QTableWidget *>()->item(0, 1)->setText(original);
		pump();
	}

	const std::string language = plugin->settings().interface_language;
	auto select_language = [&](const std::string &code) {
		auto *picker = nav_group->parent()->findChild<QComboBox *>("mrLanguage");
		int index = picker->findData(qs(code));
		if (index < 0 || picker->itemIcon(index).pixmap(picker->iconSize()).isNull())
			return false;
		picker->setCurrentIndex(index);
		picker->activated(index);
		pump();
		auto *active = nav_group->parent()->findChild<QComboBox *>("mrLanguage");
		return active->currentData().toString() == qs(code) && nav_group->button(0)->text() == T("Overview") &&
		       (code == "en" || T("Interface language") != "Interface language") &&
		       load_settings({plugin->settings_path()}, plugin->env()).interface_language == code;
	};
	bool rebuilt = true;
	for (const auto &entry : languages())
		rebuilt &= select_language(entry.first);
	rebuilt &= select_language(language);

	bool unchanged = plugin->settings().to_json() == before;
	return std::format("pages {}, toggles {}, sliders {}, radios {}, keys {} ({}), file name {}, names table {}, language switch {}, "
			   "settings unchanged: {}",
			   pages_seen, toggles, sliders, radios, keys, keys_ok ? "ok" : "WRONG", template_ok ? "ok" : "WRONG",
			   table_ok ? "ok" : "WRONG", rebuilt ? "ok" : "WRONG", unchanged ? "yes" : "NO");
}

// ---------------------------------------------------------------- Overview

QWidget *SettingsWindow::page_overview()
{
	Look look = look_of(this);
	QVBoxLayout *body;
	QWidget *page = page_of(T("Overview"), body);

	auto *banner = new QFrame();
	banner->setObjectName("mrBanner");
	auto *banner_line = new QHBoxLayout(banner);
	banner_line->setContentsMargins(14, 12, 14, 12);
	banner_line->setSpacing(12);
	banner_line->addWidget(glyph_label(G_WARNING, look.warn, 18), 0, Qt::AlignTop);
	auto *banner_text = new QLabel(QString("<b>%1</b><br/>%2")
					       .arg(T("The old Moment Replays script is still loaded, so the plugin is paused"),
						    T("Clips are being handled by the script. Remove it in Tools, Scripts (select "
						      "Moment_Replays.py, press the minus button) and the plugin takes over by itself.")));
	banner_text->setWordWrap(true);
	banner_line->addWidget(banner_text, 1);
	body->addWidget(banner);

	auto *status = new Card();
	Row buffer = make_row(T("Replay buffer"), {}, G_RECORD);
	Row next = make_row(T("Next clip goes to"), {}, G_FOLDER);
	Row scene = make_row(T("Auto scene"), {}, G_GAME);
	Row keys = make_row(T("Key presses"), T("Only while your game is the window in front"), G_KEYBOARD);
	auto state_label = [&](Row &row) {
		auto *label = new QLabel();
		row.controls->addWidget(label);
		return label;
	};
	QLabel *buffer_state = state_label(buffer), *next_state = state_label(next), *scene_state = state_label(scene),
	       *keys_state = state_label(keys);
	next_state->setWordWrap(true);
	next_state->setAlignment(Qt::AlignRight | Qt::AlignVCenter);
	next_state->setMinimumWidth(380);
	for (Row *row : {&buffer, &next, &scene, &keys})
		status->add(row->widget);
	body->addWidget(status);

	body->addWidget(heading(T("Last clip")));
	auto *clip_card = new Card();
	Row clip = make_row({}, {}, G_VIDEO);
	auto *open = button(T("Open"), G_PLAY, this);
	auto *reveal = button(T("Show in folder"), G_OPEN_FOLDER, this);
	clip.controls->addWidget(open);
	clip.controls->addWidget(reveal);
	clip_card->add(clip.widget);
	body->addWidget(clip_card);
	connect(open, &QPushButton::clicked, this, [this] { plugin->open_last_video(); });
	connect(reveal, &QPushButton::clicked, this, [this] { show_in_folder(qs(plugin->last_clip().path)); });

	auto *attention_title = heading(T("Needs attention"));
	body->addWidget(attention_title);
	auto *attention = new Card();
	body->addWidget(attention);
	body->addStretch(1);

	auto dot = [look](bool on, const QString &text) {
		return QString("<span style='color:%1'>●</span>&nbsp; %2").arg((on ? look.ok : look.muted).name(), text.toHtmlEscaped());
	};
	refreshers.push_back([=, this] {
		if (pages->currentIndex() != 0)
			return;
		const Settings &s = plugin->settings();
		bool paused = plugin->paused_by_script();
		banner->setVisible(paused);
		QString save_key = qs(plugin->obs_save_key_text());
		const_cast<Row &>(buffer).set_sub(save_key.isEmpty() ? T("No key is bound to Save Replay in OBS")
								     : T("Save Replay in OBS is %1").arg(save_key));
		buffer_state->setText(obs_frontend_replay_buffer_active()
					      ? dot(true, T("On, last %1 s").arg(plugin->replay_buffer_seconds()))
					      : dot(false, T("Off")));

		auto problems = plugin->folder_problems();
		bool broken = problems.count("clips_base_path");
		fs::path base = broken ? u8path(plugin->obs_recording_path()) : plugin->base_path();
		bool by_scene = s.clips_naming_mode == 2;
		next_state->setText(soft(native(path_u8(base)) + "\\<" + (by_scene ? T("scene") : T("game")) + ">\\"));
		const_cast<Row &>(next).set_sub(by_scene ? QString()
							 : T("Listed apps save to %1").arg(native(path_u8(base / u8path(s.app_other_folder))) + "\\"));

		QString detail = qs(plugin->auto_scene_detail());
		QString scene_text, scene_sub;
		bool scene_on = false;
		switch (plugin->auto_scene_state()) {
		case AutoSceneState::Off:
			scene_text = T("Off");
			break;
		case AutoSceneState::WaitingScenes:
			scene_text = T("Waiting");
			scene_sub = T("Scenes \"%1\" and \"%2\" must both exist").arg(qs(s.auto_scene_game), qs(s.auto_scene_desktop));
			break;
		case AutoSceneState::OtherObs:
			scene_text = T("Paused");
			scene_sub = T("Another OBS is running, so its game hook is left alone");
			break;
		case AutoSceneState::Checking:
			scene_text = T("Starting...");
			break;
		case AutoSceneState::WaitingSource:
			scene_text = T("Waiting");
			scene_sub = T("Game capture source \"%1\" was not found").arg(qs(s.auto_scene_game_source));
			break;
		default:
			scene_on = true;
			scene_text = T("On");
			scene_sub = detail.isEmpty() ? T("Waiting for a fullscreen game")
				    : detail == "*"  ? T("%1 is capturing a game").arg(qs(s.auto_scene_game_source))
						     : T("%1 has hooked %2").arg(qs(s.auto_scene_game_source), detail);
		}
		if (paused)
			scene_text = T("Paused"), scene_on = false;
		scene_state->setText(dot(scene_on, scene_text));
		const_cast<Row &>(scene).set_sub(scene_sub);
		keys_state->setText(!s.record_inputs ? dot(false, T("Off"))
				    : paused         ? dot(false, T("Paused"))
				    : plugin->keys_recording_now() ? dot(true, T("Recording"))
								   : dot(false, T("On, waiting for the game")));

		const LastClip &last = plugin->last_clip();
		bool has_clip = !last.path.empty();
		open->setEnabled(has_clip);
		reveal->setEnabled(has_clip);
		if (last.failed) {
			clip.title->setText(T("The last clip could not be moved"));
			const_cast<Row &>(clip).set_sub(T("It stays where OBS saved it. See the OBS log for the reason."));
		} else if (!has_clip) {
			clip.title->setText(T("No clip saved yet"));
			const_cast<Row &>(clip).set_sub(T("Save a replay and it shows up here."));
		} else {
			QFileInfo file(qs(last.path));
			clip.title->setText(file.fileName());
			const QLocale locale(qs(s.interface_language));
			QStringList parts = {T("%1 s").arg(locale.toString(last.duration, 'f', 1))};
			if (last.marks)
				parts << T("Markers: %1").arg(last.marks);
			if (last.info == "...")
				parts << T("writing clip info...");
			else if (last.info == "mp4")
				parts << (last.keys ? T("clip info and key presses stored") : T("clip info stored"));
			else if (last.info == "json")
				parts << T("clip info in a .moment.json file");
			const_cast<Row &>(clip).set_sub(parts.join(", ") + ". " +
							T("Saved %1 to %2").arg(ago(last.saved_at, locale), QDir::toNativeSeparators(file.path()) + "\\"));
		}

		// Problems: rebuilt each time, they are few.
		while (attention->box->count()) {
			QLayoutItem *item = attention->box->takeAt(0);
			if (item->widget())
				item->widget()->deleteLater();
			delete item;
		}
		auto problem_row = [&](const QString &title, const QString &sub, bool error = false) {
			attention->add(make_row(title, sub, error ? G_ERROR : G_WARNING, false, error ? look.bad : look.warn).widget);
		};
		static const std::map<std::string, const char *> folder_names = {{"clips_base_path", "Clips folder"},
										  {"clips_override_path", "Second clips folder"},
										  {"recording_alt_folder", "Recordings folder"},
										  {"clips_links_folder_path", "Shared folder"}};
		for (auto &[key, problem] : problems)
			problem_row(T(folder_names.at(key)) + ": " + native(problem.path), folder_problem_text(problem), true);
		if (s.show_override_folder_settings && !plugin->ffmpeg_found())
			problem_row(T("Short clips need ffmpeg"),
				    T("ffmpeg was not found in PATH. Until it is, the short clip hotkey saves the full clip."));
		bool any = attention->box->count() > 0;
		attention->setVisible(any);
		attention_title->setVisible(any);
	});
	return page;
}

// ---------------------------------------------------------------- Folders

QWidget *SettingsWindow::page_folders()
{
	Look look = look_of(this);
	QVBoxLayout *body;
	QWidget *page = page_of(T("Folders"), body);
	const Settings &s = plugin->settings();

	// A folder field: type or browse; `set` stores it.
	auto folder_field = [this](Row &row, const std::string &value, const QString &placeholder,
				   std::function<void(Settings &, const std::string &)> set) {
		auto *edit = new QLineEdit(native(value));
		edit->setFont(mono());
		edit->setFixedWidth(270);
		edit->setPlaceholderText(placeholder);
		auto *browse = button(T("Browse"));
		row.controls->addWidget(edit);
		row.controls->addWidget(browse);
		connect(edit, &QLineEdit::editingFinished, this, [this, edit, set] {
			std::string path = edit->text().trimmed().toStdString();
			commit([&](Settings &next) { set(next, path); });
		});
		connect(browse, &QPushButton::clicked, this, [this, edit, set] {
			QString chosen = QFileDialog::getExistingDirectory(this, {}, edit->text());
			if (chosen.isEmpty())
				return;
			edit->setText(QDir::toNativeSeparators(chosen));
			std::string path = edit->text().toStdString();
			commit([&](Settings &next) { set(next, path); });
		});
		return edit;
	};

	auto *main_card = new Card();
	Row clips = make_row(T("Clips folder"), T("Each game or scene gets its own folder inside"));
	QLineEdit *clips_edit = folder_field(clips, s.clips_base_path, T("The OBS recording folder"),
					     [](Settings &next, const std::string &path) { next.clips_base_path = path; });
	auto *use_obs = button(T("Use OBS folder"));
	clips.controls->addWidget(use_obs);
	connect(use_obs, &QPushButton::clicked, this, [this, clips_edit] {
		clips_edit->clear();
		commit([](Settings &next) { next.clips_base_path.clear(); });
	});
	main_card->add(clips.widget);
	body->addWidget(main_card);

	body->addWidget(heading(T("Extra hotkeys")));
	auto *extra_card = new Card();
	Row extra = make_row(T("Second folder, short clip, separate recordings"), T("Off: these three hotkeys do nothing"));
	auto *extra_toggle = new ToggleSwitch();
	extra_toggle->setChecked(s.show_override_folder_settings);
	extra.controls->addWidget(extra_toggle);
	connect(extra_toggle, &ToggleSwitch::toggled, this,
		[this](bool on) { commit([&](Settings &next) { next.show_override_folder_settings = on; }); });

	Row second = make_row(T("Second clips folder"), T("Empty: the clips folder"), 0, true);
	QLabel *second_key = key_label({});
	second.controls->addWidget(second_key);
	folder_field(second, s.clips_override_path, {}, [](Settings &next, const std::string &path) { next.clips_override_path = path; });

	Row recordings = make_row(T("Recordings folder"), T("Full recordings, any drive. Empty: the clips folder"), 0, true);
	QLabel *recordings_key = key_label({});
	recordings.controls->addWidget(recordings_key);
	folder_field(recordings, s.recording_alt_folder, {},
		     [](Settings &next, const std::string &path) { next.recording_alt_folder = path; });

	Row brief = make_row(T("Short clip"), {}, 0, true);
	QLabel *brief_key = key_label({});
	auto *percent = new QSlider(Qt::Horizontal);
	percent->setRange(1, 20); // 5 % steps
	percent->setValue(s.short_buffer_percent / 5);
	percent->setFixedWidth(180);
	auto *percent_label = new QLabel();
	percent_label->setFixedWidth(44);
	percent_label->setAlignment(Qt::AlignRight | Qt::AlignVCenter);
	brief.controls->addWidget(brief_key);
	brief.controls->addWidget(percent);
	brief.controls->addWidget(percent_label);
	connect(percent, &QSlider::valueChanged, this, [this](int value) { commit([&](Settings &next) { next.short_buffer_percent = value * 5; }); });

	for (Row *row : {&extra, &second, &recordings, &brief})
		extra_card->add(row->widget);
	body->addWidget(extra_card);

	body->addWidget(heading(T("Shared folder")));
	auto *shared_card = new Card();
	Row shared = make_row(T("Also collect all clips in one folder"), T("Every clip appears here too and takes no extra space"));
	folder_field(shared, s.clips_links_folder_path, {},
		     [](Settings &next, const std::string &path) { next.clips_links_folder_path = path; });
	auto *shared_toggle = new ToggleSwitch();
	shared_toggle->setChecked(s.clips_create_links);
	shared.controls->addWidget(shared_toggle);
	connect(shared_toggle, &ToggleSwitch::toggled, this, [this](bool on) { commit([&](Settings &next) { next.clips_create_links = on; }); });
	shared_card->add(shared.widget);
	body->addWidget(shared_card);

	body->addWidget(heading(T("Folder for selected apps")));
	auto *other_card = new Card();
	auto *other_holder = new QWidget();
	auto *other_box = new QHBoxLayout(other_holder);
	other_box->setContentsMargins(14, 12, 14, 12);
	other_box->setSpacing(14);
	auto *apps = button({});
	apps->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
	auto *menu = new QMenu(apps);
	apps->setMenu(menu);
	auto *list = new QListWidget();
	list->setAccessibleName(T("Folder for selected apps"));
	list->setSelectionMode(QAbstractItemView::ExtendedSelection);
	for (auto &name : s.app_other_names)
		list->addItem(qs(name));
	auto update_count = [apps, list] { apps->setText(T("Apps (%1)").arg(list->count())); };
	update_count();
	auto *items = new QWidgetAction(menu);
	items->setDefaultWidget(list);
	menu->addAction(items);
	menu->addSeparator();
	auto *add = menu->addAction(T("Add app"));
	auto *recent = menu->addMenu(T("Add from recent apps"));
	auto *remove = menu->addAction(T("Remove selected"));
	remove->setEnabled(false);
	connect(list, &QListWidget::itemSelectionChanged, menu, [=] { remove->setEnabled(!list->selectedItems().isEmpty()); });
	connect(menu, &QMenu::aboutToShow, menu, [=] {
		menu->setMinimumWidth(apps->width());
		list->setFixedHeight(std::clamp(list->count(), 1, 8) * std::max(list->sizeHintForRow(0), list->fontMetrics().height() + 4)
				     + 2 * list->frameWidth());
	});
	auto *folder = new QLineEdit(qs(s.app_other_folder));
	folder->addAction(glyph_icon(G_FOLDER, look.text, 18), QLineEdit::LeadingPosition);
	folder->setAccessibleName(T("Folder name"));
	folder->setToolTip(T("Folder name"));
	other_box->addWidget(apps, 1);
	other_box->addWidget(glyph_label(G_FORWARD, look.muted, 18));
	other_box->addWidget(folder, 1);
	connect(folder, &QLineEdit::editingFinished, this, [this, folder] {
		std::string name = folder->text().trimmed().toStdString();
		if (!valid_app_folder(name)) {
			folder->setText(qs(plugin->settings().app_other_folder));
			QMessageBox::warning(this, T("Folder name"), T("Enter a single valid Windows folder name."));
			return;
		}
		folder->setText(qs(name));
		commit([&](Settings &next) { next.app_other_folder = name; });
	});
	other_card->add(other_holder);
	body->addWidget(other_card);
	body->addStretch(1);

	auto add_other = [this, list, update_count](const QString &name) {
		QString value = name.trimmed();
		if (value.isEmpty() || !list->findItems(value, Qt::MatchFixedString).isEmpty())
			return;
		if (value.contains('>') || value.contains('\\') || value.contains('/') || value.contains(':')) {
			QMessageBox::warning(this, "Moment Replays", T("Use app names only: no paths and none of > / \\ :"));
			return;
		}
		list->addItem(value);
		update_count();
		commit([&](Settings &next) { next.app_other_names.push_back(value.toStdString()); });
	};
	connect(add, &QAction::triggered, this, [this, add_other] {
		add_other(QInputDialog::getText(this, "Moment Replays", T("App name, as it appears in clip names:")));
	});
	connect(recent, &QMenu::aboutToShow, this, [this, add_other, recent] {
		recent->clear();
		for (auto &exe : plugin->recent_apps()) {
			QString name = qs(exe_stem(exe));
			connect(recent->addAction(name), &QAction::triggered, this, [add_other, name] { add_other(name); });
		}
		if (recent->isEmpty())
			recent->addAction(T("No apps seen yet"))->setEnabled(false);
	});
	connect(remove, &QAction::triggered, this, [this, list, update_count] {
		qDeleteAll(list->selectedItems());
		update_count();
		std::vector<std::string> names;
		for (int i = 0; i < list->count(); i++)
			names.push_back(list->item(i)->text().toStdString());
		commit([&](Settings &next) { next.app_other_names = names; });
	});

	Row clips_copy = clips, second_copy = second, recordings_copy = recordings, brief_copy = brief, shared_copy = shared;
	refreshers.push_back([=, this]() mutable {
		if (pages->currentIndex() != 1)
			return;
		const Settings &now = plugin->settings();
		auto problems = plugin->folder_problems();
		auto note = [&](Row &row, const char *key, const QString &fine = {}) {
			auto found = problems.find(key);
			if (found != problems.end())
				row.set_note(folder_problem_text(found->second), look.bad);
			else
				row.set_note(fine, look.ok);
		};
		QString next_clip = native(path_u8(plugin->base_path())) + "\\<" + (now.clips_naming_mode == 2 ? T("scene") : T("game")) + ">\\";
		note(clips_copy, "clips_base_path", T("Next clip: %1").arg(next_clip));
		if (problems.count("clips_base_path") && !now.clips_base_path.empty())
			clips_copy.set_note(clips_copy.note->text() + " " + T("Until then clips stay in the OBS recording folder."), look.bad);
		use_obs->setVisible(!now.clips_base_path.empty());
		clips_edit->setPlaceholderText(native(plugin->obs_recording_path()));

		bool on = now.show_override_folder_settings;
		for (Row *row : {&second_copy, &recordings_copy, &brief_copy})
			row->widget->setEnabled(on);
		note(second_copy, "clips_override_path");
		note(recordings_copy, "recording_alt_folder");
		note(shared_copy, "clips_links_folder_path");
		auto key_text = [&](const char *name) {
			QString text = qs(plugin->hotkey_text(name));
			return text.isEmpty() ? T("No key") : text;
		};
		second_key->setText(key_text("save_buffer_override_folder"));
		recordings_key->setText(key_text("record_alternative_folder"));
		brief_key->setText(key_text("save_buffer_half"));
		percent_label->setText(QString("%1 %").arg(now.short_buffer_percent));
		int seconds = plugin->replay_buffer_seconds();
		brief_copy.set_sub(T("Keeps the last %1 s of your %2 s buffer").arg(seconds * now.short_buffer_percent / 100).arg(seconds));
	});
	return page;
}

// ---------------------------------------------------------------- Naming

QWidget *SettingsWindow::page_naming()
{
	Look look = look_of(this);
	QVBoxLayout *body;
	QWidget *page = page_of(T("Naming"), body);
	const Settings &s = plugin->settings();

	auto *top = new QHBoxLayout();
	top->setSpacing(10);
	auto *modes = new Card();
	auto *mode_group = new QButtonGroup(modes);
	const char *mode_names[] = {"Active app at save time", "App active for most of the replay", "Current scene"};
	for (int i = 0; i < 3; i++) {
		auto *holder = new QWidget();
		auto *line = new QHBoxLayout(holder);
		line->setContentsMargins(14, 11, 14, 11);
		auto *radio = new QRadioButton(T(mode_names[i]));
		radio->setChecked(s.clips_naming_mode == i);
		mode_group->addButton(radio, i);
		line->addWidget(radio);
		modes->add(holder);
	}
	connect(mode_group, &QButtonGroup::idClicked, this, [this](int id) { commit([&](Settings &next) { next.clips_naming_mode = id; }); });
	top->addWidget(modes, 1);

	auto *name_card = new Card();
	auto *name_holder = new QWidget();
	auto *name_box = new QVBoxLayout(name_holder);
	name_box->setContentsMargins(14, 10, 14, 12);
	name_box->setSpacing(7);
	auto *name_title = new QLabel(T("File name"));
	name_title->setObjectName("mrRowTitle");
	auto *tmpl = new QLineEdit(qs(s.clips_filename_template));
	tmpl->setFont(mono());
	auto *preview = new QLabel();
	auto *chips = new QHBoxLayout();
	chips->setSpacing(5);
	for (const char *code : {"%NAME", "%d", "%m", "%Y", "%H", "%M", "%S"}) {
		auto *chip = new QPushButton(code);
		chip->setObjectName("mrChip");
		chip->setFont(mono());
		chip->setAutoDefault(false);
		chips->addWidget(chip);
		connect(chip, &QPushButton::clicked, this, [tmpl, code] {
			tmpl->insert(code);
			tmpl->setFocus();
		});
	}
	chips->addStretch(1);
	tmpl->setToolTip(T("%NAME: clip name. %d day, %m month, %Y year, %y short year, %H hour, %I 12-hour, %p AM/PM, %M minute, "
			   "%S second, %f microsecond, %a %A weekday, %b %B month name, %j day of the year, %U %W week. %z and %Z produce no text."));
	name_box->addWidget(name_title);
	name_box->addWidget(tmpl);
	name_box->addWidget(preview);
	name_box->addLayout(chips);
	name_card->add(name_holder);
	top->addWidget(name_card, 1);
	body->addLayout(top);

	auto show_preview = [=] {
		try {
			preview->setText(qs(gen_filename_now("Deadlock", tmpl->text().toStdString())) + ".mp4");
			preview->setStyleSheet(QString("color:%1;font-size:12px").arg(look.ok.name()));
			return true;
		} catch (const FilenameError &error) {
			preview->setText(error.kind == FilenameError::Format ? T("Invalid file name format.")
									      : T("A file name can't contain / \\ : \" < > * ? | %"));
			preview->setStyleSheet(QString("color:%1;font-size:12px").arg(look.bad.name()));
			return false;
		}
	};
	connect(tmpl, &QLineEdit::textChanged, this, [this, tmpl, show_preview] {
		if (show_preview()) // a template that can't make a name is never saved
			commit([&](Settings &next) { next.clips_filename_template = tmpl->text().toStdString(); });
	});
	show_preview();

	body->addWidget(heading(T("Game names")));
	auto *table_card = new Card();
	auto *table = new QTableWidget(0, 2);
	table->setHorizontalHeaderLabels({T("Program or folder"), T("Clip name")});
	table->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
	table->verticalHeader()->setVisible(false);
	table->setSelectionBehavior(QAbstractItemView::SelectRows);
	table->setFrameShape(QFrame::NoFrame);
	table->setMinimumHeight(230);
	auto add_table_row = [table](const QString &left, const QString &right) {
		int row = table->rowCount();
		table->insertRow(row);
		auto *first = new QTableWidgetItem(left);
		first->setFont(mono());
		table->setItem(row, 0, first);
		table->setItem(row, 1, new QTableWidgetItem(right));
	};
	auto split = [](const std::string &rule) {
		size_t at = rule.find('>');
		return std::pair{qs(trim(rule.substr(0, at))), qs(at == std::string::npos ? "" : trim(rule.substr(at + 1)))};
	};
	for (auto &rule : s.app_name_replacements)
		add_table_row(split(rule).first, split(rule).second);
	for (auto &rule : s.aliases_list)
		add_table_row(split(rule).first, split(rule).second);

	// The table is the two lists of the settings: a row with a path is a path name, any other an .exe name fix.
	auto store_table = [this, table] {
		std::vector<std::string> aliases, fixes;
		for (int row = 0; row < table->rowCount(); row++) {
			QString left = table->item(row, 0) ? table->item(row, 0)->text().trimmed() : QString();
			QString right = table->item(row, 1) ? table->item(row, 1)->text().trimmed() : QString();
			if (left.isEmpty() && right.isEmpty())
				continue;
			bool is_path = left.contains('\\') || left.contains('/') || left.contains(':');
			(is_path ? aliases : fixes).push_back((left + " > " + right).toStdString());
		}
		commit([&](Settings &next) {
			next.aliases_list = aliases;
			next.app_name_replacements = fixes;
		});
	};
	connect(table, &QTableWidget::itemChanged, this, [this, store_table] {
		if (!building)
			store_table();
	});

	auto *table_holder = new QWidget();
	auto *table_box = new QVBoxLayout(table_holder);
	table_box->setContentsMargins(1, 1, 1, 10);
	table_box->addWidget(table);
	auto *table_buttons = new QHBoxLayout();
	table_buttons->setContentsMargins(13, 4, 13, 0);
	auto *add = button(T("Add"), G_ADD, this);
	auto *add_recent = button(T("Add from recent apps"));
	auto *remove = button(T("Remove selected"));
	auto *import = button(T("Import"));
	auto *export_button = button(T("Export"));
	for (QPushButton *b : {add, add_recent, remove})
		table_buttons->addWidget(b);
	table_buttons->addStretch(1);
	table_buttons->addWidget(import);
	table_buttons->addWidget(export_button);
	table_box->addLayout(table_buttons);
	table_card->add(table_holder);
	body->addWidget(table_card, 1);
	body->addWidget(hint(T("A full path or folder wins over a program name. Without a rule the clip is named after the .exe file. "
			       "Double-click a cell to edit it.")));

	connect(add, &QPushButton::clicked, this, [this, table, add_table_row] {
		QSignalBlocker block(table);
		add_table_row({}, {});
		table->editItem(table->item(table->rowCount() - 1, 0));
	});
	connect(add_recent, &QPushButton::clicked, this, [this, table, add_table_row, add_recent, store_table] {
		QMenu menu(this);
		for (auto &exe : plugin->recent_apps()) {
			QString stem = qs(exe_stem(exe));
			connect(menu.addAction(stem), &QAction::triggered, this, [this, table, add_table_row, stem, store_table] {
				QString name = QInputDialog::getText(this, "Moment Replays", T("Clip name for %1:").arg(stem), QLineEdit::Normal, stem);
				if (name.trimmed().isEmpty())
					return;
				{
					QSignalBlocker block(table);
					add_table_row(stem, name.trimmed());
				}
				store_table();
			});
		}
		if (menu.isEmpty())
			menu.addAction(T("No apps seen yet"))->setEnabled(false);
		menu.exec(add_recent->mapToGlobal(QPoint(0, add_recent->height())));
	});
	connect(remove, &QPushButton::clicked, this, [table, store_table] {
		QSet<int> rows;
		for (auto *item : table->selectedItems())
			rows.insert(item->row());
		QList<int> sorted = rows.values();
		std::sort(sorted.begin(), sorted.end(), std::greater<int>());
		{
			QSignalBlocker block(table);
			for (int row : sorted)
				table->removeRow(row);
		}
		store_table();
	});
	connect(export_button, &QPushButton::clicked, this, [this] {
		QString file = QFileDialog::getSaveFileName(this, {}, "moment_replays_names.json", "JSON (*.json)");
		if (file.isEmpty())
			return;
		const Settings &now = plugin->settings();
		json out = {{"aliases_list", now.aliases_list}, {"app_name_replacements", now.app_name_replacements}};
		try {
			write_file_atomic(u8path(file.toStdString()), out.dump(2) + "\n");
		} catch (const std::exception &) {
			QMessageBox::warning(this, "Moment Replays", T("The file could not be written."));
		}
	});
	connect(import, &QPushButton::clicked, this, [this] {
		QString file = QFileDialog::getOpenFileName(this, {}, {}, "JSON (*.json)");
		auto text = file.isEmpty() ? std::nullopt : read_file(u8path(file.toStdString()));
		if (!text)
			return;
		json parsed = json::parse(*text, nullptr, false);
		Settings from = Settings::from_json(parsed.is_array() ? json{{"aliases_list", parsed}} : parsed, plugin->env());
		bool has_aliases = parsed.is_array() || (parsed.is_object() && parsed.contains("aliases_list"));
		bool has_fixes = parsed.is_object() && parsed.contains("app_name_replacements");
		if (!has_aliases && !has_fixes) {
			QMessageBox::warning(this, "Moment Replays", T("This file has no naming rules."));
			return;
		}
		commit([&](Settings &next) {
			if (has_aliases)
				next.aliases_list = from.aliases_list;
			if (has_fixes)
				next.app_name_replacements = from.app_name_replacements;
		});
		build();
	});
	return page;
}

// ---------------------------------------------------------------- Hotkeys

QWidget *SettingsWindow::page_hotkeys()
{
	QVBoxLayout *body;
	QWidget *page = page_of(T("Hotkeys"), body);

	struct Item {
		const char *name;
		ushort icon;
		const char *title;
	};
	const Item items[] = {{"save_buffer_half", G_CUT, "Save short clip"},
			      {"save_buffer_override_folder", G_MOVE, "Save to the second folder"},
			      {"open_last_video", G_PLAY, "Open last saved video"},
			      {"record_alternative_folder", G_RECORD, "Start or stop recording into the recordings folder"},
			      {"mark_moment", G_FLAG, "Mark moment"}};
	auto *card = new Card();
	std::vector<std::pair<Row, KeyButton *>> rows;
	for (auto &item : items) {
		Row row = make_row(T(item.title), {}, item.icon);
		auto *key = new KeyButton(plugin, item.name);
		auto *clear = new QPushButton();
		clear->setIcon(glyph_icon(G_CLOSE, palette().color(QPalette::ButtonText), 12));
		clear->setToolTip(T("Remove the key"));
		clear->setAutoDefault(false);
		clear->setFixedWidth(30);
		row.controls->addWidget(key);
		row.controls->addWidget(clear);
		connect(clear, &QPushButton::clicked, this, [this, name = std::string(item.name)] { plugin->set_hotkey_bindings(name, json::array()); });
		card->add(row.widget);
		rows.emplace_back(row, key);
	}
	body->addWidget(card);

	body->addWidget(heading(T("In OBS")));
	auto *obs_card = new Card();
	Row save = make_row(T("Save Replay"), T("OBS's own key. Change it in OBS Settings, Hotkeys."), G_SAVE);
	QLabel *save_key = key_label({});
	save.controls->addWidget(save_key);
	obs_card->add(save.widget);
	body->addWidget(obs_card);
	body->addWidget(hint(T("The same keys also show in OBS Settings, Hotkeys under [Moment Replays]. A change in either place is kept.")));
	body->addStretch(1);

	refreshers.push_back([=, this]() mutable {
		if (pages->currentIndex() != 3)
			return;
		const Settings &s = plugin->settings();
		int seconds = plugin->replay_buffer_seconds();
		bool extra = s.show_override_folder_settings;
		QString off = T("Off: turn on Extra hotkeys on the Folders page");
		rows[0].first.set_sub(!extra ? off : T("The last %1 % of the replay (%2 s)").arg(s.short_buffer_percent).arg(seconds * s.short_buffer_percent / 100));
		rows[1].first.set_sub(!extra ? off : native(s.clips_override_path.empty() ? path_u8(plugin->base_path()) : s.clips_override_path));
		rows[2].first.set_sub(T("Waits for a save that is still being written"));
		rows[3].first.set_sub(!extra ? off : native(s.recording_alt_folder.empty() ? path_u8(plugin->base_path()) : s.recording_alt_folder));
		rows[4].first.set_sub(T("The next clip that contains this moment shows it in Moment Player"));
		for (auto &[row, key] : rows)
			key->show_binding();
		QString text = qs(plugin->obs_save_key_text());
		save_key->setText(text.isEmpty() ? T("No key") : text);
	});
	return page;
}

// ---------------------------------------------------------------- Sounds

QWidget *SettingsWindow::page_sounds()
{
	QVBoxLayout *body;
	QWidget *page = page_of(T("Sounds"), body);
	const Settings &s = plugin->settings();

	auto *main_card = new Card();
	Row master = make_row(T("Play sounds"));
	auto *master_toggle = new ToggleSwitch();
	master_toggle->setChecked(s.sound_notification_settings);
	master.controls->addWidget(master_toggle);
	connect(master_toggle, &ToggleSwitch::toggled, this, [this](bool on) { commit([&](Settings &next) { next.sound_notification_settings = on; }); });

	Row volume = make_row(T("Volume"));
	auto *slider = new QSlider(Qt::Horizontal);
	slider->setRange(0, 20);
	slider->setValue(s.sound_volume / 5);
	slider->setFixedWidth(240);
	auto *volume_label = new QLabel(QString("%1 %").arg(s.sound_volume));
	volume_label->setFixedWidth(44);
	volume_label->setAlignment(Qt::AlignRight | Qt::AlignVCenter);
	auto *test = button(T("Test"), G_PLAY, this);
	volume.controls->addWidget(slider);
	volume.controls->addWidget(volume_label);
	volume.controls->addWidget(test);
	connect(slider, &QSlider::valueChanged, this, [this, volume_label](int value) {
		volume_label->setText(QString("%1 %").arg(value * 5));
		commit([&](Settings &next) { next.sound_volume = value * 5; });
	});
	connect(test, &QPushButton::clicked, this, [this] { plugin->play_test_sound(); });
	main_card->add(master.widget);
	main_card->add(volume.widget);
	body->addWidget(main_card);

	body->addWidget(heading(T("Events")));
	auto *events = new Card();
	struct Event {
		const char *title;
		bool Settings::*enabled;
		std::string Settings::*path;
	};
	const Event list[] = {
		{"Clip saved", &Settings::notify_clips_on_success, &Settings::notify_clips_on_success_path},
		{"Clip failed", &Settings::notify_clips_on_failure, &Settings::notify_clips_on_failure_path},
		{"Recording started", &Settings::notify_recording_on_start, &Settings::notify_recording_on_start_path},
		{"Recording stopped", &Settings::notify_recording_on_stop, &Settings::notify_recording_on_stop_path},
	};
	for (auto &event : list) {
		Row row = make_row(T(event.title));
		auto *toggle = new ToggleSwitch();
		toggle->setChecked(s.*event.enabled);
		row.line->insertWidget(0, toggle);
		auto *file = new QLabel();
		file->setFont(mono());
		file->setFixedWidth(230);
		auto show_file = [file](const std::string &path) {
			QFileInfo info(qs(path));
			file->setText(file->fontMetrics().elidedText(info.fileName(), Qt::ElideMiddle, 226));
			file->setToolTip(QDir::toNativeSeparators(info.filePath()));
		};
		show_file(s.*event.path);
		auto *play = new QPushButton();
		play->setIcon(glyph_icon(G_PLAY, palette().color(QPalette::ButtonText), 12));
		play->setFixedWidth(30);
		play->setAutoDefault(false);
		auto *choose = button(T("Choose file"));
		row.controls->addWidget(file);
		row.controls->addWidget(play);
		row.controls->addWidget(choose);
		events->add(row.widget);
		auto enabled = event.enabled;
		auto path = event.path;
		connect(toggle, &ToggleSwitch::toggled, this, [this, enabled](bool on) { commit([&](Settings &next) { next.*enabled = on; }); });
		connect(play, &QPushButton::clicked, this, [this, path] { plugin->play_sound_file(plugin->settings().*path); });
		connect(choose, &QPushButton::clicked, this, [this, path, show_file] {
			QString chosen = QFileDialog::getOpenFileName(this, {}, qs(plugin->settings().*path), "WAV (*.wav)");
			if (chosen.isEmpty())
				return;
			std::string value = QDir::toNativeSeparators(chosen).toStdString();
			commit([&](Settings &next) { next.*path = value; });
			show_file(value);
		});
	}
	body->addWidget(events);
	body->addWidget(hint(T("WAV files only. Mark moment plays a short blip of the Clip saved sound.")));
	body->addStretch(1);
	return page;
}

// ---------------------------------------------------------------- Moments

QWidget *SettingsWindow::page_moments()
{
	QVBoxLayout *body;
	QWidget *page = page_of(T("Moments"), body);
	const Settings &s = plugin->settings();

	auto *scene_card = new Card();
	Row automatic = make_row(T("Auto-switch Game and Desktop scenes"),
				 T("Shows the game scene once the capture has hooked your fullscreen game, the desktop scene otherwise. "
				   "Pauses while another OBS is running."));
	auto *auto_toggle = new ToggleSwitch();
	auto_toggle->setChecked(s.auto_scene_enabled);
	automatic.controls->addWidget(auto_toggle);
	connect(auto_toggle, &ToggleSwitch::toggled, this, [this](bool on) { commit([&](Settings &next) { next.auto_scene_enabled = on; }); });
	scene_card->add(automatic.widget);

	auto picker = [&](const char *title, const std::string &value, std::vector<std::string> options, std::string Settings::*field) {
		Row row = make_row(T(title), {}, 0, true);
		auto *combo = new QComboBox();
		combo->setEditable(true);
		combo->setMinimumWidth(220);
		if (std::find(options.begin(), options.end(), value) == options.end())
			options.insert(options.begin(), value);
		for (auto &option : options)
			combo->addItem(qs(option));
		combo->setCurrentText(qs(value));
		row.controls->addWidget(combo);
		auto store = [this, combo, field] {
			std::string text = combo->currentText().trimmed().toStdString();
			if (!text.empty())
				commit([&](Settings &next) { next.*field = text; });
		};
		connect(combo, &QComboBox::activated, this, store);
		connect(combo->lineEdit(), &QLineEdit::editingFinished, this, store);
		scene_card->add(row.widget);
	};
	picker("Game scene", s.auto_scene_game, plugin->scene_names(), &Settings::auto_scene_game);
	picker("Desktop scene", s.auto_scene_desktop, plugin->scene_names(), &Settings::auto_scene_desktop);
	picker("Game capture source", s.auto_scene_game_source, plugin->game_capture_names(), &Settings::auto_scene_game_source);
	body->addWidget(scene_card);

	auto *info_card = new Card();
	Row info = make_row(T("Store clip info inside the clip"),
			    T("Game, app timeline, marks, audio track names and encoder settings for Moment Player. Stored in the MP4 "
			      "itself; other formats get a .moment.json file next to the clip."));
	auto *info_toggle = new ToggleSwitch();
	info_toggle->setChecked(s.write_moment_metadata);
	info.controls->addWidget(info_toggle);
	connect(info_toggle, &ToggleSwitch::toggled, this, [this](bool on) { commit([&](Settings &next) { next.write_moment_metadata = on; }); });
	info_card->add(info.widget);
	body->addWidget(info_card);

	auto *keys_card = new Card();
	Row keys = make_row(T("Record key presses"),
			    T("When clip info is enabled, Moment Player can show which buttons you pressed and when. "
			      "Anyone with the MP4 or the .moment.json file can see this. Off by default."));
	auto *keys_toggle = new ToggleSwitch();
	keys_toggle->setChecked(s.record_inputs);
	keys.controls->addWidget(keys_toggle);
	connect(keys_toggle, &ToggleSwitch::toggled, this, [this](bool on) { commit([&](Settings &next) { next.record_inputs = on; }); });
	keys_card->add(keys.widget);

	auto *detail = new QWidget();
	auto *detail_line = new QHBoxLayout(detail);
	detail_line->setContentsMargins(42, 12, 14, 14);
	detail_line->setSpacing(20);
	QPixmap picture(qs(path_u8(plugin->env().data_dir / "Moment_Input_Overlay.png")));
	if (!picture.isNull()) {
		auto *image = new QLabel();
		image->setPixmap(picture.scaledToWidth(300, Qt::SmoothTransformation));
		detail_line->addWidget(image, 0, Qt::AlignTop);
	}
	auto *detail_text = new QVBoxLayout();
	auto *recorded = new QLabel(T("Recorded, and nothing else"));
	recorded->setObjectName("mrRowTitle");
	detail_text->addWidget(recorded);
	detail_text->addWidget(new QLabel("1 2 3 4 5   Q W E R T   A S D F G   Z X C V\nShift  Ctrl  Alt  Space  Tab\n" + T("Mouse buttons")));
	detail_text->addWidget(hint(T("Only records input when the active window is detected as a game. The desktop, known browsers, "
				      "chats, terminals and apps in your folder list are excluded. Key presses are never written to the OBS log.")));
	detail_text->addStretch(1);
	detail_line->addLayout(detail_text, 1);
	keys_card->add(detail);
	body->addWidget(keys_card);
	body->addStretch(1);
	return page;
}

// ---------------------------------------------------------------- Updates

QWidget *SettingsWindow::page_updates()
{
	Look look = look_of(this);
	QVBoxLayout *body;
	QWidget *page = page_of(T("Updates"), body);

	auto *card = new Card();
	Row status = make_row({}, {}, G_SYNC);
	auto *check = button(T("Check now"));
	auto *release = button(T("Open the release page"));
	status.controls->addWidget(check);
	status.controls->addWidget(release);
	card->add(status.widget);
	body->addWidget(card);
	connect(check, &QPushButton::clicked, this, [this] { plugin->check_updates(true); });
	connect(release, &QPushButton::clicked, this, [this] {
		const UpdateResult *result = plugin->update_result();
		QDesktopServices::openUrl(QUrl(qs(result && !result->release_url.empty()
							  ? result->release_url
							  : std::string("https://github.com/") + UPDATE_REPO + "/releases/latest")));
	});

	body->addWidget(heading(T("OBS start")));
	auto *start_card = new Card();
	Row crash = make_row(T("Don't ask about Safe Mode after a crash"),
			     T("After a crash or a forced close OBS asks at its next start whether to run in Safe Mode. With this on it "
			       "does not ask, unless OBS failed while starting. Safe Mode stays available: start OBS with --safe-mode. "
			       "Turning this off takes effect from the next OBS start."));
	auto *crash_toggle = new ToggleSwitch();
	crash_toggle->setChecked(plugin->settings().skip_crash_prompt);
	crash.controls->addWidget(crash_toggle);
	connect(crash_toggle, &ToggleSwitch::toggled, this, [this](bool on) { commit([&](Settings &next) { next.skip_crash_prompt = on; }); });
	start_card->add(crash.widget);
	body->addWidget(start_card);

	body->addWidget(heading(T("Settings")));
	auto *file_card = new Card();
	Row file = make_row(T("Settings file"), QDir::toNativeSeparators(qs(path_u8(plugin->settings_path()))));
	auto *reveal = button(T("Show in folder"), G_OPEN_FOLDER, this);
	file.controls->addWidget(reveal);
	connect(reveal, &QPushButton::clicked, this, [this] { show_in_folder(qs(path_u8(plugin->settings_path()))); });
	file_card->add(file.widget);
	if (!plugin->imported_from().empty())
		file_card->add(make_row(T("Taken over from the script"),
					T("Folders, naming rules, sounds and hotkeys were read from %1. That file was not changed.")
						.arg(native(plugin->imported_from())))
				       .widget);
	body->addWidget(file_card);
	body->addStretch(1);

	refreshers.push_back([=, this]() mutable {
		if (pages->currentIndex() != 6)
			return;
		const UpdateResult *result = plugin->update_result();
		check->setEnabled(!plugin->update_running());
		ushort icon = G_SYNC;
		QColor color = look.text;
		QString title, sub;
		if (plugin->update_running()) {
			title = T("Checking for updates...");
		} else if (!result) {
			title = T("Moment Replays %1").arg(VERSION);
			sub = T("Not checked yet. Updates install by themselves and start with the next OBS start.");
		} else {
			QString latest = qs(result->latest);
			switch (result->state) {
			case UpdateResult::Current:
				icon = G_OK, color = look.ok;
				title = T("Moment Replays %1 is up to date").arg(VERSION);
				sub = T("Updates install by themselves and start with the next OBS start.");
				break;
			case UpdateResult::Installed:
				icon = G_DOWNLOAD, color = look.ok;
				title = T("Version %1 is installed").arg(latest);
				sub = T("Restart OBS to use it. Running now: %1.").arg(VERSION);
				break;
			case UpdateResult::Available: {
				icon = G_WARNING, color = look.warn;
				title = T("Version %1 is available but was not installed").arg(latest);
				const std::string &why = result->reason;
				sub = why == "update_reason_dev"       ? T("This is a development build.")
				      : why == "update_reason_tag"     ? T("The release has an unexpected version tag.")
				      : why == "update_reason_damaged" ? T("%1 was damaged on the way.").arg(qs(result->detail))
				      : why == "update_reason_folder"  ? T("The plugin folder can't be written.")
								       : T("That release has no files for the plugin.");
				break;
			}
			case UpdateResult::NoRelease:
				title = T("Moment Replays %1").arg(VERSION);
				sub = T("No release is published yet.");
				break;
			default:
				icon = G_ERROR, color = look.bad;
				title = T("Update check failed");
				sub = T("See the OBS log for details. OBS will check again the next time it starts.");
			}
		}
		set_glyph(status.icon, icon, color);
		status.title->setText(title);
		status.set_sub(sub);
	});
	return page;
}

} // namespace mr
