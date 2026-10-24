// The Orange Pi models a SorterOS image exists for. `id` goes into the
// image's /etc/sorteros-config.toml as `board`; it matches BOARD in the
// image's /etc/orangepi-release, so the machine can tell a wrong pick from
// the board it runs on.
//
// `wifi` is what the page says about the model's Wi-Fi: the board decides
// whether the setup network (SorterOS-Setup-XXXXXX) exists at all.

export interface Board {
    id: string;
    label: string;
    help: string;
    wifi: string;
}

export const BOARDS: Board[] = [
    {
        id: 'orangepi5',
        label: 'Orange Pi 5',
        help: 'The image for the Orange Pi 5 (RK3588S).',
        wifi: 'The onboard Wi-Fi is the AP6275P on the M.2 card; without it use Ethernet.'
    },
    {
        id: 'orangepi5pro',
        label: 'Orange Pi 5 Pro',
        help: 'The image for the Orange Pi 5 Pro (RK3588S), built from the Pro vendor image.',
        wifi: 'Wi-Fi is onboard (AP6256).'
    }
];

export const DEFAULT_BOARD = BOARDS[0].id;
